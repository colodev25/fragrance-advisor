"""Nightly queue lifecycle and persistent budgets, without external requests."""
import copy
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src import ingest, catalog_jobs as jobs
from src.catalog_integrity import atomic_write_json
from src.catalog_enrichment import enrichment_signature


@pytest.fixture
def raw():
    return {"id": 1, "title": "Test", "handle": "test", "tags": ["Unisex"],
            "body_html": "Una composizione con iris e sandalo",
            "variants": [{"id": 2, "price": "90", "available": True}]}


@pytest.fixture
def product(raw):
    return ingest.transform_product(raw, "https://example.com", allow_llm=False)


def success_result():
    return {"notes": [{"name": "Iris", "position": None, "source": "description", "evidence": "con iris e sandalo"}],
            "family": None, "successful": True}


def test_sync_never_calls_groq_and_preserves_cache_for_stock_and_price_changes(raw, product, monkeypatch):
    monkeypatch.setattr(ingest, "_get_groq_client", MagicMock(side_effect=AssertionError("No Groq during sync")))
    signature = product["enrichment_input"]["signature"]
    enriched = jobs.apply_result(product, success_result(), signature)
    raw["variants"][0]["price"] = "75"
    raw["variants"][0]["available"] = False
    raw["tags"].append("20% sconto")
    unavailable = ingest.transform_product(raw, "https://example.com", enriched, allow_llm=False)
    assert unavailable["price"] == 75
    assert not unavailable["in_stock"]
    assert unavailable["unpositioned_notes"] == ["Iris"]
    raw["variants"][0]["available"] = True
    restored = ingest.transform_product(raw, "https://example.com", unavailable, allow_llm=False)
    assert restored["unpositioned_notes"] == ["Iris"]
    assert restored["enrichment_cache"] == enriched["enrichment_cache"]


def test_queue_pauses_unavailable_removes_deleted_and_resets_changed_sources(product):
    state = {"version": 1, "queue": {}, "reservations": []}
    jobs.reconcile(state, [product], [])
    assert state["queue"][product["id"]]["status"] == "pending"
    state["queue"][product["id"]].update(status="failed", attempts=3)
    unavailable = dict(product, in_stock=False)
    jobs.reconcile(state, [], [unavailable])
    assert state["queue"][product["id"]]["status"] == "out_of_stock"
    jobs.reconcile(state, [product], [])
    assert state["queue"][product["id"]]["status"] == "pending"
    changed = copy.deepcopy(product)
    changed["enrichment_input"]["description"] += " Nuova descrizione."
    jobs.reconcile(state, [changed], [])
    assert state["queue"][product["id"]]["attempts"] == 0
    jobs.reconcile(state, [], [])
    assert not state["queue"]


def test_valid_empty_response_finishes_without_repeated_requests(tmp_path, product):
    completed = jobs.apply_result(product, {"notes": [], "family": None}, product["enrichment_input"]["signature"])
    atomic_write_json(tmp_path / "catalog.json", [completed])
    client = MagicMock()
    state = jobs.run_nightly(tmp_path, client)
    assert state["queue"][product["id"]]["status"] == "no_information"
    client.chat.completions.create.assert_not_called()


def test_legacy_records_wait_for_sync_without_api_calls(tmp_path, product):
    product.pop("enrichment_input")
    atomic_write_json(tmp_path / "catalog.json", [product])
    client = MagicMock()
    state = jobs.run_nightly(tmp_path, client)
    assert state["queue"][product["id"]]["status"] == "awaiting_sync"
    client.chat.completions.create.assert_not_called()


def test_nightly_success_updates_catalog_and_reserves_usage(tmp_path, product):
    atomic_write_json(tmp_path / "catalog.json", [product])
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "notes": [{"name": "Iris", "position": None, "evidence": "con iris e sandalo"}], "family": None})), finish_reason="stop")],
        usage=SimpleNamespace(total_tokens=700))
    state = jobs.run_nightly(tmp_path, client)
    saved = json.loads((tmp_path / "catalog.json").read_text())
    assert saved[0]["unpositioned_notes"] == ["Iris"]
    assert state["queue"][product["id"]]["status"] == "completed"
    assert state["reservations"][0]["actual_tokens"] == 700
    assert state["reservations"][0]["tokens"] >= 700
    jobs.run_nightly(tmp_path, client)
    assert client.chat.completions.create.call_count == 1


def test_insufficient_budget_does_not_call_api_or_consume_product_attempt(tmp_path, product):
    atomic_write_json(tmp_path / "catalog.json", [product])
    client = MagicMock()
    state = jobs.run_nightly(tmp_path, client, token_limit=1)
    client.chat.completions.create.assert_not_called()
    assert state["queue"][product["id"]]["attempts"] == 0
    assert not state["reservations"]


def test_manual_reruns_keep_reserved_budget_and_retry_reservations(tmp_path, monkeypatch):
    state = jobs.load_state(tmp_path)
    batch = jobs.NightlyBudget(state, tmp_path, token_limit=5000)
    request = {"messages": [{"content": "Iris"}], "max_tokens": 2048}
    monkeypatch.setattr(jobs.time, "sleep", lambda seconds: None)
    assert batch.reserve_request(request)
    first = jobs.load_state(tmp_path)
    assert first["reservations"][0]["actual_tokens"] is None
    again = jobs.NightlyBudget(first, tmp_path, token_limit=5000)
    assert again.reserve_request(request)
    assert not again.reserve_request(request)
    assert again.stop_reason == "daily_budget"
    assert len(jobs.load_state(tmp_path)["reservations"]) == 2


def test_failed_response_is_deferred_without_changing_product(tmp_path, product):
    atomic_write_json(tmp_path / "catalog.json", [product])
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="invalid JSON"), finish_reason="stop")])
    state = jobs.run_nightly(tmp_path, client)
    entry = state["queue"][product["id"]]
    assert entry["status"] == "failed"
    assert entry["next_attempt_at"] > jobs.utc_now().isoformat()
    assert json.loads((tmp_path / "catalog.json").read_text()) == [product]
    jobs.run_nightly(tmp_path, client)
    assert client.chat.completions.create.call_count == 1


def test_expired_reservations_are_removed_and_corrupt_ledger_is_not_reset(tmp_path, product):
    state = jobs.load_state(tmp_path)
    state["reservations"] = [{"at": (jobs.utc_now() - timedelta(hours=25)).isoformat(), "tokens": 40000}]
    jobs.reconcile(state, [product], [])
    assert state["reservations"] == []
    atomic_write_json(tmp_path / jobs.STATE_NAME, {"version": 1, "queue": {}, "reservations": [{"tokens": "bad"}]})
    with pytest.raises(ValueError):
        jobs.load_state(tmp_path)
