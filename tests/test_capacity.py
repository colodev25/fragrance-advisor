"""Offline admission, streaming payload and shared Groq capacity regressions."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import RateLimitError, APITimeoutError
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import src.capacity as capacity
import src.main as api
from src.chat_budget import ChatBudget, ChatUnavailable
from src.llm_resilience import ResilientGroqClient


PAYLOAD = {"message": "iris", "session_id": "customer", "session_key": "b" * 64}


@pytest.fixture
def client(monkeypatch):
    advisor = MagicMock()
    advisor.advise.return_value = {"reply": "Risposta", "products": []}
    monkeypatch.setattr(api, "advisor", advisor)
    monkeypatch.setattr(capacity, "provider_capacity", capacity.ProviderCapacity())
    api.rate_limiter.reset()
    # No lifespan: this API-only fixture must not initialize the index/provider.
    instance = TestClient(api.app)
    try:
        yield instance, advisor
    finally:
        instance.close()


@pytest.mark.parametrize("path", ["/chat", "/chat/", "/reset", "/reset/"])
def test_oversized_body_is_rejected_before_advisor_with_cors(client, path):
    instance, advisor = client
    response = instance.post(path, content=b"x" * 16385, headers={"Origin": "https://store.test"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert "access-control-allow-origin" in response.headers
    advisor.advise.assert_not_called()
    advisor.reset_session.assert_not_called()


@pytest.mark.parametrize("path,payload", [
    ("/chat", {**PAYLOAD, "unexpected": "value"}),
    ("/chat", {**PAYLOAD, "session_context": {"token": "a" * 32, "revision": 1, "extra": True}}),
    ("/reset", {"session_id": "customer", "session_key": "b" * 64, "extra": True}),
])
def test_extra_fields_are_rejected(client, path, payload):
    instance, advisor = client
    assert instance.post(path, json=payload).status_code == 422
    advisor.advise.assert_not_called()
    advisor.reset_session.assert_not_called()


def test_two_workers_reject_excess_without_queue_and_health_remains_ready(client):
    instance, advisor = client
    entered = [Event(), Event()]
    release = Event()
    def work(**kwargs):
        entered[int(kwargs["session_id"][-1])].set()
        assert release.wait(5)
        return {"reply": "Risposta"}
    advisor.advise.side_effect = work
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = [executor.submit(instance.post, "/chat", json={**PAYLOAD, "session_id": f"customer{i}"}) for i in range(2)]
        try:
            assert all(event.wait(5) for event in entered)
            response = instance.post("/chat", json=PAYLOAD, headers={"Origin": "https://store.test"})
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "service_capacity_exceeded"
            assert response.headers["Retry-After"] == "2"
            assert "retry-after" in response.headers["access-control-expose-headers"].lower()
            assert instance.get("/health").status_code == 200
            assert advisor.advise.call_count == 2
        finally:
            release.set()
        assert all(future.result().status_code == 200 for future in pending)
    advisor.advise.side_effect = None
    assert instance.post("/chat", json=PAYLOAD).status_code == 200


def test_exception_and_invalid_json_release_admission(client):
    instance, advisor = client
    for _ in range(3):
        assert instance.post("/chat", content=b"{").status_code == 422
    advisor.advise.side_effect = RuntimeError("simulated")
    for _ in range(3):
        assert instance.post("/chat", json=PAYLOAD).status_code == 503
    advisor.advise.side_effect = None
    assert instance.post("/chat", json=PAYLOAD).status_code == 200


def test_api_workers_share_provider_budget_but_model_free_paths_still_work(client, monkeypatch):
    instance, advisor = client
    guard = capacity.ProviderCapacity(limit=1)
    monkeypatch.setattr(capacity, "provider_capacity", guard)
    sdk = MagicMock()
    sdk.with_options.return_value = sdk
    sdk.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content="Risposta"), finish_reason="stop")])
    wrapper = ResilientGroqClient(sdk)
    def work(**kwargs):
        reply = wrapper.create_completion([{"role": "user", "content": kwargs["user_query"]}], chat_budget=ChatBudget())
        return {"reply": reply}
    advisor.advise.side_effect = work
    assert instance.post("/chat", json=PAYLOAD).status_code == 200
    blocked = instance.post("/chat", json={**PAYLOAD, "session_id": "other"})
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "llm_rate_limit"
    assert int(blocked.headers["Retry-After"]) > 0
    assert sdk.chat.completions.create.call_count == 1
    advisor.advise.side_effect = None
    assert instance.post("/chat", json={**PAYLOAD, "session_id": "third"}).status_code == 200
    assert capacity.current_provider_capacity.get() is None


def test_echoed_expiry_is_validated_but_never_used_as_session_authority(client):
    instance, advisor = client
    context = {"token": "a" * 32, "revision": 1, "expires_at": 9_007_199_254_740_991}
    assert instance.post("/chat", json={**PAYLOAD, "session_context": context}).status_code == 200
    assert advisor.advise.call_args.kwargs["session_context"] == {"token": "a" * 32, "revision": 1}
    assert instance.post("/chat", json={**PAYLOAD, "session_context": {**context, "expires_at": "invalid"}}).status_code == 422


def test_forged_forwarded_header_is_not_read_by_application(client):
    instance, _ = client
    first = instance.post("/chat", json=PAYLOAD, headers={"X-Forwarded-For": "1.2.3.4"})
    assert first.status_code == 200
    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"forged")], "client": ("actual", 123)}
    assert api._client_identifier(Request(scope)) == "actual"


@pytest.mark.parametrize("peer,expected", [("trusted", "1.2.3.4"), ("untrusted", "untrusted")])
def test_uvicorn_only_normalizes_forwarded_client_for_trusted_peer(peer, expected):
    async def scenario():
        clients = []
        async def app(scope, receive, send):
            clients.append(api._client_identifier(Request(scope)))
        proxy = ProxyHeadersMiddleware(app, trusted_hosts=["trusted"])
        await proxy({"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4")],
                     "client": (peer, 123)}, None, None)
        assert clients == [expected]
    asyncio.run(scenario())


@pytest.mark.parametrize("mode,status", [("chunked", 413), ("lying_length", 413), ("slow", 408), ("disconnect", None), ("encoding", 415)])
def test_streamed_bodies_are_bounded_and_slots_released(mode, status):
    async def scenario():
        called = []
        async def app(scope, receive, send):
            called.append(True)
        gate = capacity.AdmissionGate(1)
        middleware = capacity.CapacityMiddleware(app, gate, max_bytes=16, body_timeout=0.01)
        chunks = [b"a" * 10, b"b" * 10]
        headers = [(b"content-length", b"1")] if mode == "lying_length" else []
        if mode == "encoding":
            headers = [(b"content-encoding", b"gzip")]
        async def receive():
            if mode == "slow":
                await asyncio.sleep(10)
            if mode == "disconnect":
                return {"type": "http.disconnect"}
            return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}
        sent = []
        async def send(event):
            sent.append(event)
        await middleware({"type": "http", "method": "POST", "path": "/chat", "headers": headers}, receive, send)
        assert gate.active == 0
        assert not called
        if status is not None:
            assert sent[0]["status"] == status
    asyncio.run(scenario())


def test_cancelled_http_task_keeps_slot_until_worker_finishes():
    async def scenario():
        gate = capacity.AdmissionGate(1)
        started, release, ended = Event(), Event(), Event()
        def work():
            started.set()
            release.wait(5)
            ended.set()
            raise RuntimeError("abandoned worker")
        async def app(scope, receive, send):
            await capacity.run_admitted(Request(scope), work)
        middleware = capacity.CapacityMiddleware(app, gate)
        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}
        task = asyncio.create_task(middleware({"type": "http", "method": "POST", "path": "/chat", "headers": []}, receive, None))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert gate.active == 1
            assert not gate.acquire()
        finally:
            release.set()
        assert await asyncio.to_thread(ended.wait, 5)
        for _ in range(100):
            if gate.active == 0:
                break
            await asyncio.sleep(0.01)
        assert gate.active == 0
    asyncio.run(scenario())


def test_provider_allowance_is_shared_rolling_and_atomic():
    now = [100.0]
    guard = capacity.ProviderCapacity(limit=2, clock=lambda: now[0])
    def reserve():
        try:
            guard.reserve()
            return True
        except ChatUnavailable:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(lambda _: reserve(), range(8))) == 2
    now[0] += 59
    with pytest.raises(ChatUnavailable) as error:
        guard.reserve()
    assert error.value.retry_after == 1
    now[0] += 1
    guard.reserve()


@pytest.mark.parametrize("hint,expected", [(None, 5), ("40", 40), ("0.5", 1)])
def test_provider_rate_limit_stops_fallback_and_blocks_other_chat(hint, expected):
    guard = capacity.ProviderCapacity(clock=lambda: 100)
    sdk = MagicMock()
    sdk.with_options.return_value = sdk
    headers = {} if hint is None else {"Retry-After": hint}
    sdk.chat.completions.create.side_effect = RateLimitError("simulated", body=None,
        response=httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://provider.test")))
    token = capacity.current_provider_capacity.set(guard)
    try:
        for _ in range(2):
            with pytest.raises(ChatUnavailable) as error:
                ResilientGroqClient(sdk).create_completion([{"role": "user", "content": "iris"}], chat_budget=ChatBudget())
            assert error.value.retry_after == expected
        assert sdk.chat.completions.create.call_count == 1
    finally:
        capacity.current_provider_capacity.reset(token)


def test_retries_count_against_global_allowance_without_extra_sdk_call(monkeypatch):
    guard = capacity.ProviderCapacity(limit=1)
    sdk = MagicMock()
    sdk.with_options.return_value = sdk
    sdk.chat.completions.create.side_effect = APITimeoutError(request=httpx.Request("POST", "https://provider.test"))
    monkeypatch.setattr("src.llm_resilience.time.sleep", lambda _: None)
    token = capacity.current_provider_capacity.set(guard)
    try:
        with pytest.raises(ChatUnavailable, match="llm_rate_limit"):
            ResilientGroqClient(sdk).create_completion([{"role": "user", "content": "iris"}], chat_budget=ChatBudget())
        assert sdk.chat.completions.create.call_count == 1
    finally:
        capacity.current_provider_capacity.reset(token)
