"""Coordinamento chat/reset e recupero dei risultati, senza servizi esterni."""

import sqlite3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.advisor import FragranceAdvisor
from src.conversation_requests import RequestConflict, SessionCoordinator, session_coordinator
from src.session_store import SessionStore
import src.main as api


def make_advisor(store):
    # Usa il vero flusso advise senza inizializzare ricerca o client remoti.
    advisor = FragranceAdvisor.__new__(FragranceAdvisor)
    advisor.session_store = store
    advisor.sessions = defaultdict(list)
    advisor.active_perfumes = {}
    advisor.guided_states = defaultdict(lambda: {"step": None, "answers": []})

    def reply(message, session_id, max_price):
        answer = {"reply": "Risposta a " + message, "options": [], "products": [], "step": None}
        advisor.sessions[session_id].extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer["reply"]},
        ])
        return answer

    advisor._handle_free_chat = MagicMock(side_effect=reply)
    return advisor


@pytest.fixture
def advisor(tmp_path):
    return make_advisor(SessionStore(str(tmp_path / "requests.db")))


def test_duplicate_returns_result_without_processing_or_state_change(advisor):
    first = advisor.advise("iris", "customer", request_id="req_1")
    original = advisor.session_store.get_session("customer")
    again = advisor.advise(" iris ", "customer", request_id="req_1")
    assert again == first
    assert advisor._handle_free_chat.call_count == 1
    assert advisor.session_store.get_session("customer") == original


def test_receipt_survives_advisor_and_store_restart(advisor):
    expected = advisor.advise("iris", "customer", request_id="req_1")
    restarted = make_advisor(SessionStore(str(advisor.session_store.db_path)))
    assert restarted.advise("iris", "customer", request_id="req_1") == expected
    restarted._handle_free_chat.assert_not_called()


@pytest.mark.parametrize("changed", [
    {"user_query": "rosa"}, {"max_price": 90}, {"step_override": 2},
])
def test_id_conflict_rejects_changed_payload(advisor, changed):
    advisor.advise("iris", "customer", request_id="req_1")
    args = {"user_query": "iris", "session_id": "customer", "request_id": "req_1", **changed}
    with pytest.raises(RequestConflict) as error:
        advisor.advise(**args)
    assert error.value.code == "request_id_conflict"
    assert advisor._handle_free_chat.call_count == 1


def test_identifiers_are_scoped_to_session_and_optional(advisor):
    advisor.advise("iris", "first", request_id="req_1")
    advisor.advise("rosa", "second", request_id="req_1")
    advisor.advise("iris", "first")
    advisor.advise("iris", "first")
    assert advisor._handle_free_chat.call_count == 4


def test_same_request_in_parallel_is_processed_once(advisor):
    entered, release = Event(), Event()
    original = advisor._handle_free_chat.side_effect

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    advisor._handle_free_chat.side_effect = delayed
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(advisor.advise, "iris", "customer", request_id="req_1")
        try:
            assert entered.wait(5)
            duplicate = executor.submit(advisor.advise, "iris", "customer", request_id="req_1")
            with pytest.raises(TimeoutError):
                duplicate.result(timeout=0.1)
        finally:
            release.set()
        assert first.result(timeout=5) == duplicate.result(timeout=5)
    assert advisor._handle_free_chat.call_count == 1
    assert len(advisor.session_store.get_session("customer")["history"]) == 2


def test_parallel_messages_preserve_all_exchanges(advisor):
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(advisor.advise, f"iris {i}", "customer", request_id=f"req_{i}")
                   for i in range(20)]
        for future in futures:
            future.result(timeout=10)
    history = advisor.session_store.get_session("customer")["history"]
    assert len(history) == 40
    assert {message["content"] for message in history if message["role"] == "user"} == {
        f"iris {i}" for i in range(20)
    }
    for index in range(0, 40, 2):
        assert history[index + 1]["content"] == "Risposta a " + history[index]["content"]
    assert session_coordinator._entries == {}


def test_reset_waits_for_active_chat_and_other_sessions_continue(advisor):
    entered, release, reset_started = Event(), Event(), Event()
    original = advisor._handle_free_chat.side_effect

    def delayed(message, session_id, max_price):
        if session_id == "customer":
            entered.set()
            assert release.wait(5)
        return original(message, session_id, max_price)

    def reset():
        reset_started.set()
        advisor.reset_session("customer")

    advisor._handle_free_chat.side_effect = delayed
    with ThreadPoolExecutor(max_workers=3) as executor:
        chat = executor.submit(advisor.advise, "iris", "customer", request_id="req_1")
        try:
            assert entered.wait(5)
            reset_future = executor.submit(reset)
            assert reset_started.wait(5)
            with pytest.raises(TimeoutError):
                reset_future.result(timeout=0.1)
            unrelated = executor.submit(advisor.advise, "rosa", "other", request_id="req_1")
            assert unrelated.result(timeout=5)["reply"] == "Risposta a rosa"
        finally:
            release.set()
        chat.result(timeout=5)
        reset_future.result(timeout=5)
    assert advisor.session_store.get_session("customer")["history"] == []
    assert "customer" not in advisor.sessions
    with advisor.session_store._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat_requests WHERE session_id = 'customer'").fetchone()[0] == 0
    assert len(advisor.session_store.get_session("other")["history"]) == 2


def test_failure_before_commit_can_be_retried_without_partial_history(advisor):
    original = advisor._handle_free_chat.side_effect

    def failure(message, session_id, max_price):
        advisor.sessions[session_id].append({"role": "user", "content": "partial"})
        raise RuntimeError("simulated outage")

    advisor._handle_free_chat.side_effect = failure
    with pytest.raises(RuntimeError):
        advisor.advise("iris", "customer", request_id="req_1")
    assert advisor.session_store.get_session("customer")["history"] == []
    assert session_coordinator._entries == {}
    advisor._handle_free_chat.side_effect = original
    advisor.advise("iris", "customer", request_id="req_1")
    assert len(advisor.session_store.get_session("customer")["history"]) == 2


def test_completed_fallback_response_is_reused(advisor):
    advisor._handle_free_chat.side_effect = None
    advisor._handle_free_chat.return_value = {"reply": "Riprova tra poco", "products": []}
    result = advisor.advise("iris", "customer", request_id="req_1")
    assert result["reply"] == "Riprova tra poco"
    assert result["products"] == []
    assert result["session_context"]["revision"] == 1
    advisor.advise("iris", "customer", request_id="req_1")
    assert advisor._handle_free_chat.call_count == 1


def test_state_and_receipt_rollback_together(advisor):
    store = advisor.session_store
    store.save_session("customer", [{"original": True}], None, {}, "req_1", "hash", {"reply": "original"})
    with pytest.raises(sqlite3.IntegrityError):
        store.save_session("customer", [{"partial": True}], None, {}, "req_1", "hash", {"reply": "partial"})
    assert store.get_session("customer")["history"] == [{"original": True}]
    assert store.get_request_response("customer", "req_1", "hash") == {"reply": "original"}


def test_pruned_result_keeps_identity_without_reprocessing(advisor, monkeypatch):
    monkeypatch.setattr("src.session_store.MAX_STORED_RESPONSES", 2)
    advisor.advise("other", "other", request_id="req_1")
    for index in range(3):
        advisor.advise(f"iris {index}", "customer", request_id=f"req_{index}")
    with pytest.raises(RequestConflict) as error:
        advisor.advise("iris 0", "customer", request_id="req_0")
    assert error.value.code == "request_result_expired"
    advisor.advise("iris 2", "customer", request_id="req_2")
    advisor.advise("other", "other", request_id="req_1")
    assert advisor._handle_free_chat.call_count == 4


def test_initialization_migrates_existing_database(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, history TEXT NOT NULL, active_perfume TEXT, guided_state TEXT NOT NULL, updated_at TIMESTAMP NOT NULL)")
        conn.execute("INSERT INTO sessions VALUES ('existing', '[]', NULL, '{}', '2026-10-01')")
    store = SessionStore(str(database))
    assert store.get_session("existing")["history"] == []
    store.save_session("existing", [], None, {}, "req_1", "hash", {"reply": "ok"})
    assert store.get_request_response("existing", "req_1", "hash") == {"reply": "ok"}


def test_lock_registry_cleans_up_after_nested_use_and_exception():
    coordinator = SessionCoordinator()
    with pytest.raises(RuntimeError):
        with coordinator.hold("customer"):
            with coordinator.hold("customer"):
                assert coordinator._entries["customer"]["users"] == 2
                raise RuntimeError("test")
    assert coordinator._entries == {}


@pytest.fixture
def client(advisor, monkeypatch):
    monkeypatch.setattr(api, "advisor", advisor)
    api.rate_limiter.reset()
    # Senza context manager: il lifespan non carica indice o SDK reali.
    return TestClient(api.app)


def test_api_identified_request_replay_and_conflict(client, advisor):
    payload = {"message": "iris", "session_id": "customer", "request_id": "req_1"}
    first = client.post("/chat", json=payload)
    replay = client.post("/chat/", json=payload)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    conflict = client.post("/chat", json={**payload, "message": "rosa"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "request_id_conflict"
    assert advisor._handle_free_chat.call_count == 1


@pytest.mark.parametrize("request_id", ["", "with spaces", "a" * 129, 42, {}, []])
def test_api_rejects_invalid_request_ids(client, request_id):
    response = client.post("/chat", json={"message": "iris", "session_id": "customer", "request_id": request_id})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_api_reset_removes_receipts(client, advisor):
    client.post("/chat", json={"message": "iris", "session_id": "customer", "request_id": "req_1"})
    assert client.post("/reset", json={"session_id": "customer"}).status_code == 200
    assert advisor.session_store.get_session("customer")["history"] == []
    with advisor.session_store._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat_requests").fetchone()[0] == 0


def test_api_http_failure_keeps_same_id_retryable(client, advisor):
    original = advisor._handle_free_chat.side_effect
    advisor._handle_free_chat.side_effect = RuntimeError("simulated failure")
    payload = {"message": "iris", "session_id": "customer", "request_id": "req_1"}
    assert client.post("/chat", json=payload).status_code == 503
    advisor._handle_free_chat.side_effect = original
    assert client.post("/chat", json=payload).status_code == 200
