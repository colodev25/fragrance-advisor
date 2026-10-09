"""Session lifecycle and version checks; all storage and clients are local."""
import asyncio
import sqlite3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import src.advisor as advisor_module
import src.main as api
import src.session_store as store_module
from src.advisor import FragranceAdvisor
from src.conversation_requests import RequestConflict, session_coordinator
from src.session_store import SessionStore, SESSION_TTL_SECONDS
from tests.test_conversation_requests import make_advisor


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(now=datetime(2026, 10, 8, 12, tzinfo=timezone.utc).timestamp())
    fake_time = SimpleNamespace(time=lambda: clock.now)
    monkeypatch.setattr(store_module, "time", fake_time)
    monkeypatch.setattr(advisor_module, "time", fake_time)
    return clock


@pytest.fixture
def advisor(tmp_path, clock):
    return make_advisor(SessionStore(str(tmp_path / "lifecycle.db")))


def test_ttl_renews_only_for_completed_new_messages(advisor, clock):
    first = advisor.advise("iris", "customer", request_id="req_1", session_key="b" * 64)
    context = first["session_context"]
    assert context["expires_at"] == int((clock.now + SESSION_TTL_SECONDS) * 1000)
    clock.now += 100
    assert advisor.advise("iris", "customer", request_id="req_1", session_key="b" * 64) == first
    assert advisor.session_store.get_session("customer")["session_context"] == context
    second = advisor.advise("rosa", "customer", session_context=context, request_id="req_2", session_key="b" * 64)
    assert second["session_context"]["token"] == context["token"]
    assert second["session_context"]["revision"] == 2
    assert second["session_context"]["expires_at"] == int((clock.now + SESSION_TTL_SECONDS) * 1000)


def test_expired_session_rejects_replay_without_any_processing(advisor, clock):
    first = advisor.advise("iris", "customer", request_id="req_1", session_key="b" * 64)
    clock.now += SESSION_TTL_SECONDS
    with pytest.raises(RequestConflict, match="scaduta") as error:
        advisor.advise("iris", "customer", request_id="req_1", session_context=first["session_context"], session_key="b" * 64)
    assert error.value.code == "session_expired"
    assert advisor._handle_free_chat.call_count == 1
    assert advisor.session_store.get_session("customer")["history"] == []
    assert advisor.sessions == advisor.active_perfumes == advisor.guided_states == {}


def test_missing_database_after_deploy_is_detected_before_processing(advisor, clock, tmp_path):
    first = advisor.advise("iris", "customer", session_key="b" * 64)
    advisor.session_store = SessionStore(str(tmp_path / "fresh_deploy.db"))
    with pytest.raises(RequestConflict) as error:
        advisor.advise("quanto costa", "customer", session_context=first["session_context"], session_key="b" * 64)
    assert error.value.code == "session_expired"
    assert advisor._handle_free_chat.call_count == 1


def test_same_sid_with_new_session_token_cannot_resume_old_state(advisor):
    first = advisor.advise("iris", "customer", session_key="b" * 64)
    advisor.reset_session("customer", session_key="b" * 64)
    renewed = advisor.advise("rosa", "customer", session_key="b" * 64)
    assert renewed["session_context"]["token"] != first["session_context"]["token"]
    with pytest.raises(RequestConflict) as error:
        advisor.advise("quanto costa", "customer", session_context=first["session_context"], session_key="b" * 64)
    assert error.value.code == "session_expired"


def test_stale_revision_is_rejected_without_processing(advisor):
    first = advisor.advise("iris", "customer", session_key="b" * 64)
    advisor.advise("rosa", "customer", session_context=first["session_context"], session_key="b" * 64)
    with pytest.raises(RequestConflict) as error:
        advisor.advise("altra", "customer", session_context=first["session_context"], session_key="b" * 64)
    assert error.value.code == "session_out_of_sync"
    assert advisor._handle_free_chat.call_count == 2


def test_replay_of_last_completed_request_recovers_using_original_revision(advisor):
    first = advisor.advise("iris", "customer", request_id="req_1", session_key="b" * 64)
    second = advisor.advise("rosa", "customer", request_id="req_2", session_context=first["session_context"], session_key="b" * 64)
    assert advisor.advise("rosa", "customer", request_id="req_2",
                          session_context=first["session_context"], session_key="b" * 64) == second
    assert advisor._handle_free_chat.call_count == 2
    advisor.advise("oud", "customer", session_context=second["session_context"], session_key="b" * 64)
    with pytest.raises(RequestConflict) as error:
        advisor.advise("rosa", "customer", request_id="req_2", session_context=first["session_context"], session_key="b" * 64)
    assert error.value.code == "session_out_of_sync"


def test_database_restart_retains_token_revision_and_expiry(advisor):
    first = advisor.advise("iris", "customer", request_id="req_1", session_key="b" * 64)
    restarted = make_advisor(SessionStore(str(advisor.session_store.db_path)))
    assert restarted.advise("iris", "customer", request_id="req_1", session_key="b" * 64) == first
    assert restarted.session_store.get_session("customer")["session_context"] == first["session_context"]


def test_no_inactive_customer_copies_remain_in_memory(advisor):
    for index in range(20):
        advisor.advise("iris", f"customer_{index}", session_key="b" * 64)
        assert advisor.sessions == advisor.active_perfumes == advisor.guided_states == {}
    assert session_coordinator._entries == {}


def test_connections_are_closed_after_success_and_failure(advisor):
    with advisor.session_store._get_connection() as connection:
        connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with pytest.raises(RuntimeError):
        with advisor.session_store._get_connection() as failed:
            raise RuntimeError("simulated")
    with pytest.raises(sqlite3.ProgrammingError):
        failed.execute("SELECT 1")


def expire(store, sid):
    with store._get_connection() as connection:
        connection.execute("UPDATE sessions SET expires_at = 0 WHERE session_id = ?", (sid,))


def test_cleanup_removes_state_and_receipts_together_but_keeps_fresh_sessions(advisor):
    advisor.advise("iris", "expired", request_id="req_1", session_key="b" * 64)
    advisor.advise("rosa", "fresh", request_id="req_1", session_key="b" * 64)
    expire(advisor.session_store, "expired")
    assert advisor.session_store.cleanup_old_sessions() == 1
    with advisor.session_store._get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM chat_requests").fetchone()[0] == 1


def test_cleanup_is_bounded(advisor):
    for index in range(5):
        advisor.advise("iris", f"expired_{index}", session_key="b" * 64)
        expire(advisor.session_store, f"expired_{index}")
    assert advisor.session_store.cleanup_old_sessions(limit=2) == 2
    assert advisor.session_store.cleanup_old_sessions(limit=2) == 2
    assert advisor.session_store.cleanup_old_sessions(limit=2) == 1


def test_cleanup_skips_busy_sessions_without_waiting(advisor):
    advisor.advise("iris", "customer", session_key="b" * 64)
    expire(advisor.session_store, "customer")
    with session_coordinator.hold("customer"):
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(advisor.session_store.cleanup_old_sessions).result(timeout=2) == 0
    assert advisor.session_store.cleanup_old_sessions() == 1


def test_cleanup_rechecks_expiry_after_candidate_selection(advisor, monkeypatch, clock):
    advisor.advise("iris", "customer", session_key="b" * 64)
    expire(advisor.session_store, "customer")
    original = session_coordinator.hold
    @contextmanager
    def refreshed(sid, timeout=None):
        with advisor.session_store._get_connection() as connection:
            connection.execute("UPDATE sessions SET expires_at = ? WHERE session_id = ?",
                               (clock.now + SESSION_TTL_SECONDS, sid))
        with original(sid, timeout=timeout):
            yield
    monkeypatch.setattr(session_coordinator, "hold", refreshed)
    assert advisor.session_store.cleanup_old_sessions() == 0
    assert advisor.session_store.get_session("customer")["history"]


@pytest.mark.parametrize("updated", [
    "2026-10-08T10:00:00+00:00", "2026-10-08 10:00:00", "2026-10-08T12:00:00+02:00",
])
def test_legacy_date_formats_migrate_to_same_utc_expiry(tmp_path, clock, updated):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, history TEXT NOT NULL, active_perfume TEXT, guided_state TEXT NOT NULL, updated_at TIMESTAMP NOT NULL)")
        connection.execute("INSERT INTO sessions VALUES ('customer', '[]', NULL, '{}', ?)", (updated,))
    store = SessionStore(str(path))
    context = store.get_session("customer")["session_context"]
    expected = datetime(2026, 10, 9, 10, tzinfo=timezone.utc).timestamp() * 1000
    assert context["expires_at"] == expected
    assert len(context["token"]) == 32
    assert SessionStore(str(path)).get_session("customer")["session_context"] == context


def product(identifier="p1", name="Iris", price=90):
    return {"id": identifier, "name": name, "brand": "Brand", "price": price,
            "family": "Legnosa", "ptype": "EDP", "in_stock": True,
            "semantic_text": "Note: iris", "urls": {"product_page": "https://store.test/iris"}}


def test_active_product_refreshes_by_stable_id_even_after_name_change(advisor):
    advisor.catalog_products = [product(name="Iris Nuovo", price=75)]
    refreshed = advisor._refresh_active_product({"id": "p1", "name": "Iris Vecchio", "price": 90})
    assert refreshed["name"] == "Iris Nuovo"
    assert refreshed["price"] == 75
    assert refreshed["document"] == "Note: iris"


def test_legacy_active_product_uses_only_unique_name_and_brand(advisor):
    advisor.catalog_products = [product()]
    assert advisor._refresh_active_product({"name": "Iris", "brand": "Brand"})["id"] == "p1"
    advisor.catalog_products.append(product("p2"))
    assert advisor._refresh_active_product({"name": "Iris", "brand": "Brand"}) is None


@pytest.mark.parametrize("catalog", [[], [dict(product(), in_stock=False)]])
def test_removed_or_unavailable_active_product_is_cleared_and_explained(advisor, catalog):
    advisor.catalog_products = catalog
    advisor.session_store.authorize_session("customer", "b" * 64, allow_create=True)
    advisor.session_store.save_session("customer", [], {"id": "p1", "name": "Iris"},
                                       {"step": None, "answers": []})
    result = advisor.advise("quanto costa?", "customer", session_key="b" * 64,
                           session_context=advisor.session_store.get_session("customer")["session_context"])
    assert "non è più disponibile" in result["reply"]
    assert result["products"] == []
    assert advisor.session_store.get_session("customer")["active_perfume"] is None
    advisor._handle_free_chat.assert_not_called()


@pytest.mark.parametrize("sid", [None, "", "default", "not valid", "a" * 129])
def test_advisor_requires_a_real_session_identifier(advisor, sid):
    with pytest.raises(ValueError):
        advisor.advise("iris", sid, session_key="b" * 64)
    advisor._handle_free_chat.assert_not_called()


@pytest.mark.parametrize("payload", [
    {"message": "iris"}, {"message": "iris", "session_id": None, "session_key": "b" * 64},
    {"message": "iris", "session_id": "default", "session_key": "b" * 64},
    {"message": "iris", "session_id": "customer", "session_context": {"token": "x", "revision": 1}, "session_key": "b" * 64},
    {"message": "iris", "session_id": "customer", "session_context": {"token": "a" * 32, "revision": 0}, "session_key": "b" * 64},
    {"message": "iris", "session_id": "customer", "session_context": {"token": "a" * 32, "revision": True}, "session_key": "b" * 64},
])
def test_api_rejects_missing_identifiers_and_malformed_context(advisor, monkeypatch, payload):
    monkeypatch.setattr(api, "advisor", advisor)
    api.rate_limiter.reset()
    response = TestClient(api.app).post("/chat", json=payload)
    assert response.status_code == 422
    advisor._handle_free_chat.assert_not_called()


def test_http_lost_session_returns_409_and_never_calls_processing(advisor, monkeypatch):
    monkeypatch.setattr(api, "advisor", advisor)
    api.rate_limiter.reset()
    response = TestClient(api.app).post("/chat", json={
        "message": "iris", "session_id": "customer",
        "session_context": {"token": "a" * 32, "revision": 1},
     "session_key": "b" * 64})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_expired"
    advisor._handle_free_chat.assert_not_called()


def test_maintenance_runs_bounded_batches_and_waits_between_cycles(monkeypatch):
    instance = MagicMock()
    instance.session_store.cleanup_old_sessions.side_effect = [100, 2]
    waited = []
    async def sleep(seconds):
        waited.append(seconds)
        if seconds == 3600:
            raise asyncio.CancelledError
    monkeypatch.setattr(api.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(api.maintain_sessions(instance))
    assert instance.session_store.cleanup_old_sessions.call_count == 2
    assert waited == [0, 3600]
