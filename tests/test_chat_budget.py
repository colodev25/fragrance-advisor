"""Chat budgets, provider failures and HTTP recovery without external services."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import importlib
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError, RateLimitError, OpenAI, DefaultHttpxClient

import src.chat_budget as budget_module
import src.llm_resilience as llm_module
import src.main as api
from src.advisor import FragranceAdvisor, parse_catalog_selection
from src.chat_budget import ChatBudget, ChatUnavailable, current_chat_budget
from src.conversation_requests import SessionCoordinator, session_coordinator
from src.llm_resilience import ResilientGroqClient
from src.session_store import SessionStore


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def advance(self, seconds):
        self.now += seconds

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.advance(seconds)


@pytest.fixture
def clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(budget_module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(llm_module, "time", SimpleNamespace(sleep=clock.sleep))
    return clock


def completion(text="Risposta valida", finish="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=text, reasoning_content="PRIVATO"),
        finish_reason=finish,
    )])


def limited(hint=None):
    response = httpx.Response(429, request=httpx.Request("POST", "https://provider.test"),
                              headers={} if hint is None else {"Retry-After": str(hint)})
    return RateLimitError("Simulato", response=response, body=None)


def provider():
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = completion()
    return client, ResilientGroqClient(client)


def ask(wrapper, budget, **kwargs):
    return wrapper.create_completion(
        [{"role": "user", "content": "iris"}], primary_model="openai/gpt-oss-120b",
        fallback_model="openai/gpt-oss-20b", max_tokens=2048,
        reasoning_effort="low", chat_budget=budget, **kwargs,
    )


def advisor_for(store):
    advisor = FragranceAdvisor.__new__(FragranceAdvisor)
    advisor.session_store = store
    advisor.sessions = defaultdict(list)
    advisor.active_perfumes = {}
    advisor.guided_states = defaultdict(lambda: {"step": None, "answers": []})
    client, wrapper = provider()
    advisor.client = client
    advisor.resilient_client = wrapper
    return advisor


def test_fast_response_has_explicit_sdk_settings_and_no_added_wait(clock):
    client, wrapper = provider()
    budget = ChatBudget()
    assert ask(wrapper, budget) == "Risposta valida"
    assert budget.calls == 1
    assert clock.now == 100
    assert clock.sleeps == []
    client.with_options.assert_called_once_with(max_retries=0)
    args = client.chat.completions.create.call_args.kwargs
    assert args["timeout"] == 10
    assert args["max_tokens"] == 2048
    assert args["reasoning_effort"] == "low"


def test_real_sdk_disables_its_own_retries_with_an_in_memory_transport():
    # Compatibile con SDK che usano httpx o httpx2: nessun socket o servizio reale.
    transport_module = importlib.import_module(next(
        base.__module__.split(".")[0] for base in DefaultHttpxClient.__mro__
        if base.__module__.startswith("httpx")
    ))
    requests = []
    def respond(request):
        requests.append(request)
        return transport_module.Response(429, request=request, headers={"Retry-After": "40"},
                                         json={"error": {"message": "Simulato", "type": "rate_limit"}})
    with DefaultHttpxClient(transport=transport_module.MockTransport(respond)) as http_client:
        with OpenAI(api_key="offline-test-placeholder", base_url="https://provider.test/v1",
                    max_retries=2, http_client=http_client) as sdk:
            with pytest.raises(ChatUnavailable):
                ask(ResilientGroqClient(sdk), ChatBudget())
    assert len(requests) == 1
    assert json.loads(requests[0].content)["max_tokens"] == 2048
    assert requests[0].extensions["timeout"]["read"] <= 10


def test_intent_and_generation_share_three_call_allowance(clock):
    client, wrapper = provider()
    budget = ChatBudget()
    ask(wrapper, budget, call_timeout=3, call_limit=1)
    client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
    with pytest.raises(ChatUnavailable):
        ask(wrapper, budget)
    assert budget.calls == client.chat.completions.create.call_count == 3
    assert client.chat.completions.create.call_args_list[0].kwargs["timeout"] == 3
    assert clock.sleeps == [0.8]


def test_three_failed_calls_end_without_sdk_retries(clock):
    client, wrapper = provider()
    client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
    budget = ChatBudget()
    with pytest.raises(ChatUnavailable, match="llm_timeout"):
        ask(wrapper, budget)
    assert client.chat.completions.create.call_count == 3
    assert [call.kwargs["model"] for call in client.chat.completions.create.call_args_list] == [
        "openai/gpt-oss-120b", "openai/gpt-oss-20b", "openai/gpt-oss-120b",
    ]
    assert clock.sleeps == [0.8, 0.8]


def test_exhausted_budget_cannot_make_another_provider_call(clock):
    client, wrapper = provider()
    budget = ChatBudget()
    budget.calls = budget.MAX_CALLS
    with pytest.raises(ChatUnavailable):
        ask(wrapper, budget)
    client.chat.completions.create.assert_not_called()


@pytest.mark.parametrize("text", ["", "Parziale"])
def test_truncation_never_doubles_tokens_or_returns_private_reasoning(clock, text):
    client, wrapper = provider()
    client.chat.completions.create.side_effect = [completion(text, "length"), completion("Completa")]
    assert ask(wrapper, ChatBudget()) == "Completa"
    assert client.chat.completions.create.call_count == 2
    assert all(call.kwargs["max_tokens"] == 2048 for call in client.chat.completions.create.call_args_list)
    assert clock.sleeps == []


def test_selection_validation_uses_fallback_and_rejects_unknown_ids(clock):
    client, wrapper = provider()
    client.chat.completions.create.side_effect = [
        completion('{"selection":"UNKNOWN","reply":"Inventata"}'),
        completion('{"selection":"PRODOTTO_1","reply":"Catalogo"}'),
    ]
    result = ask(wrapper, ChatBudget(), response_validator=lambda text: parse_catalog_selection(text, {"PRODOTTO_1": {}}))
    assert parse_catalog_selection(result, {"PRODOTTO_1": {}})["selection"] == "PRODOTTO_1"
    assert client.chat.completions.create.call_args.kwargs["model"] == "openai/gpt-oss-20b"


def test_invalid_completions_return_error_instead_of_successful_retry_text(clock):
    client, wrapper = provider()
    client.chat.completions.create.return_value = completion("")
    with pytest.raises(ChatUnavailable, match="llm_invalid_response"):
        ask(wrapper, ChatBudget())
    assert client.chat.completions.create.call_count == 3


@pytest.mark.parametrize("hint,wait", [("0.5", 0.8), ("1", 1.0)])
def test_short_retry_after_is_respected_without_waiting_more_than_one_second(clock, hint, wait):
    client, wrapper = provider()
    client.chat.completions.create.side_effect = [limited(hint), completion()]
    assert ask(wrapper, ChatBudget()) == "Risposta valida"
    assert clock.sleeps == [wait]


@pytest.mark.parametrize("hint", ["1.1", "40", "3600"])
def test_long_retry_after_stops_automatic_fallback_and_reports_cooldown(clock, hint):
    client, wrapper = provider()
    client.chat.completions.create.side_effect = limited(hint)
    with pytest.raises(ChatUnavailable) as caught:
        ask(wrapper, ChatBudget())
    assert caught.value.code == "llm_rate_limit"
    assert caught.value.retry_after >= float(hint)
    assert client.chat.completions.create.call_count == 1
    assert clock.sleeps == []


def test_provider_http_date_retry_after_is_supported(clock):
    client, wrapper = provider()
    hint = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=60), usegmt=True)
    client.chat.completions.create.side_effect = limited(hint)
    with pytest.raises(ChatUnavailable) as caught:
        ask(wrapper, ChatBudget())
    assert 58 <= caught.value.retry_after <= 60
    assert client.chat.completions.create.call_count == 1


def test_final_short_retry_after_is_forwarded(clock):
    client, wrapper = provider()
    client.chat.completions.create.side_effect = limited("0.5")
    with pytest.raises(ChatUnavailable) as caught:
        ask(wrapper, ChatBudget(), call_limit=1)
    assert caught.value.retry_after == 1
    assert clock.sleeps == []


def test_expired_deadline_prevents_provider_calls(clock):
    client, wrapper = provider()
    budget = ChatBudget()
    clock.advance(25)
    with pytest.raises(ChatUnavailable, match="chat_deadline_exceeded"):
        ask(wrapper, budget)
    client.chat.completions.create.assert_not_called()


def test_remaining_deadline_reduces_call_timeout(clock):
    client, wrapper = provider()
    budget = ChatBudget()
    clock.advance(23)
    ask(wrapper, budget)
    assert client.chat.completions.create.call_args.kwargs["timeout"] == 2


def test_slow_call_result_after_deadline_is_rejected(clock):
    client, wrapper = provider()
    def delayed(**kwargs):
        clock.advance(26)
        return completion()
    client.chat.completions.create.side_effect = delayed
    with pytest.raises(ChatUnavailable, match="chat_deadline_exceeded"):
        ask(wrapper, ChatBudget())
    assert client.chat.completions.create.call_count == 1


def test_deadline_prevents_an_inline_wait_or_another_call(clock):
    client, wrapper = provider()
    budget = ChatBudget()
    clock.advance(24.5)
    client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
    with pytest.raises(ChatUnavailable):
        ask(wrapper, budget)
    assert client.chat.completions.create.call_count == 1
    assert clock.sleeps == []


def test_timeout_and_cooldown_state_is_isolated_between_threads():
    with ThreadPoolExecutor(max_workers=2) as executor:
        def isolated(calls):
            budget = ChatBudget()
            token = current_chat_budget.set(budget)
            try:
                for _ in range(calls):
                    budget.reserve_call(10)
                return current_chat_budget.get().calls
            finally:
                current_chat_budget.reset(token)
        assert sorted(executor.map(isolated, [1, 2])) == [1, 2]
    assert current_chat_budget.get() is None


def test_session_lock_timeout_does_not_release_another_requests_lock():
    coordinator = SessionCoordinator()
    started = Event()
    with coordinator.hold("customer"):
        with ThreadPoolExecutor(max_workers=1) as executor:
            def waiting():
                started.set()
                with coordinator.hold("customer", timeout=0.02):
                    pytest.fail("The first request still holds the lock")
            future = executor.submit(waiting)
            assert started.wait(2)
            with pytest.raises(ChatUnavailable, match="chat_deadline_exceeded"):
                future.result(timeout=2)
        assert coordinator._entries["customer"]["users"] == 1
    assert coordinator._entries == {}


def test_failed_llm_request_preserves_state_and_can_recover_with_same_identifier(tmp_path, clock):
    store = SessionStore(str(tmp_path / "recover.db"))
    original = {"name": "Attivo"}
    store.save_session("customer", [{"role": "user", "content": "prima"}], original,
                       {"step": None, "answers": ["Legnoso"]})
    saved = store.get_session("customer")
    advisor = advisor_for(store)
    client = advisor.client
    client.chat.completions.create.side_effect = limited("40")
    def processing(query, sid, price):
        advisor.sessions[sid].append({"role": "user", "content": query})
        advisor.active_perfumes[sid] = {"name": "Parziale"}
        reply = advisor._chat_completion(messages=[{"role": "user", "content": query}])
        advisor.sessions[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "products": []}
    advisor._handle_free_chat = processing
    with pytest.raises(ChatUnavailable):
        advisor.advise("iris", "customer", request_id="req_retry")
    assert store.get_session("customer") == saved
    assert current_chat_budget.get() is None
    assert session_coordinator._entries == {}
    with store._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat_requests").fetchone()[0] == 0
    client.chat.completions.create.side_effect = None
    result = advisor.advise("iris", "customer", request_id="req_retry")
    assert result["reply"] == "Risposta valida"
    assert advisor.advise("iris", "customer", request_id="req_retry") == result
    assert client.chat.completions.create.call_count == 2


def test_expired_processing_cannot_commit_history_or_receipt(tmp_path, clock):
    store = SessionStore(str(tmp_path / "expired.db"))
    advisor = advisor_for(store)
    def slow(query, sid, price):
        advisor.sessions[sid].append({"role": "user", "content": query})
        clock.advance(26)
        return {"reply": "Troppo tardi"}
    advisor._handle_free_chat = slow
    with pytest.raises(ChatUnavailable, match="chat_deadline_exceeded"):
        advisor.advise("iris", "customer", request_id="req_1")
    assert store.get_session("customer")["history"] == []
    with store._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat_requests").fetchone()[0] == 0


def test_guided_cards_can_complete_with_fixed_intro_and_be_replayed(tmp_path, clock):
    advisor = advisor_for(SessionStore(str(tmp_path / "guided.db")))
    from tests.test_recommendation_preferences import product
    advisor.catalog_products = [product(name="Iris", tags=["unisex", "ufficio"])]
    advisor._enrich_product_payload = MagicMock(side_effect=lambda product, **kwargs: product)
    advisor.search_engine = MagicMock()
    advisor.search_engine.search.return_value = {
        "ids": [["p1"]], "metadatas": [[{"name": "Iris", "price": 90}]],
        "documents": [["Note: iris"]],
    }
    advisor.client.chat.completions.create.side_effect = limited("40")
    result = advisor.advise("Nessun limite", "customer", step_override=4, request_id="req_guided")
    assert len(result["products"]) == 1
    assert result["reply"].startswith("Ecco le fragranze selezionate")
    assert advisor.client.chat.completions.create.call_args.kwargs["max_tokens"] == 1024
    assert advisor.advise("Nessun limite", "customer", step_override=4, request_id="req_guided") == result
    assert advisor.client.chat.completions.create.call_count == 1


def test_intent_classifier_uses_one_fast_call_and_safe_fallback(clock):
    advisor = advisor_for(None)
    advisor.client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
    budget = ChatBudget()
    token = current_chat_budget.set(budget)
    try:
        assert advisor._determine_intent("Che ne pensi?", {"name": "Iris"}) == "VALUTA"
        args = advisor.client.chat.completions.create.call_args.kwargs
        assert args["timeout"] == 3
        assert args["max_tokens"] == 768
        assert budget.calls == 1
        assert clock.sleeps == []
    finally:
        current_chat_budget.reset(token)


def test_prompt_documents_prioritize_notes_and_are_bounded():
    document = "Descrizione: " + "marketing " * 1000 + "\nNote di testa: iris\nFamiglia: Legnosa"
    result = FragranceAdvisor._prompt_document(document)
    assert len(result) == 1800
    assert result.startswith("Note di testa: iris\nFamiglia: Legnosa")


def test_named_product_context_keeps_current_request_and_bounds_history(clock):
    advisor = advisor_for(None)
    product = {"name": "Iris", "price": 90, "document": "Note: iris\n" + "x" * 6000,
               "add_to_cart_url": "https://store.test/cart/1"}
    advisor._find_mentioned_product = MagicMock(return_value=product)
    advisor._enrich_product_payload = MagicMock(side_effect=lambda product, **kwargs: product)
    advisor.sessions["customer"] = [{"role": "user", "content": "a" * 5000},
                                    {"role": "assistant", "content": "b" * 5000}]
    result = advisor._handle_free_chat("Parlami di Iris", "customer", None)
    assert len(result["products"]) == 1
    messages = advisor.client.chat.completions.create.call_args.kwargs["messages"]
    assert len(messages[1]["content"]) == len(messages[2]["content"]) == 2000
    assert "Parlami di Iris" in messages[-1]["content"]
    assert "Note: iris" in messages[-1]["content"]
    assert len(messages[-1]["content"]) < 2500


@pytest.mark.parametrize("code", [
    "llm_rate_limit", "llm_timeout", "llm_unavailable", "llm_invalid_response",
    "llm_attempts_exhausted", "chat_deadline_exceeded",
])
def test_http_failures_are_retryable_and_expose_retry_after(monkeypatch, code):
    advisor = MagicMock()
    advisor.advise.side_effect = ChatUnavailable(code, 12.2)
    monkeypatch.setattr(api, "advisor", advisor)
    api.rate_limiter.reset()
    client = TestClient(api.app)
    response = client.post("/chat", headers={"Origin": "https://store.test"},
                           json={"message": "iris", "session_id": "customer", "request_id": "req_1"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == code
    assert response.headers["Retry-After"] == "13"
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()
