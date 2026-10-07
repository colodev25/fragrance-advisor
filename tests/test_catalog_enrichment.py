"""Grounded extraction and partial merging, without external API calls."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src import ingest
from src.catalog_enrichment import parse_enrichment, enrich_catalog_fields


def response(notes=None, family=None):
    return json.dumps({"notes": notes or [], "family": family})


def test_unsupported_notes_and_fabricated_quotes_are_discarded():
    text = response([
        {"name": "Vaniglia", "position": "base", "evidence": "Nel fondo iris"},
        {"name": "Iris", "position": "heart", "evidence": "Cuore di iris inventato"},
    ])
    assert parse_enrichment(text, "Nel fondo iris", [], ingest.KNOWN_FAMILIES)["notes"] == []


def test_unpositioned_and_positioned_notes_require_matching_evidence():
    text = response([
        {"name": "Iris", "position": "heart", "evidence": "iris e legni"},
        {"name": "Bergamotto", "position": "top", "evidence": "Apertura di bergamotto"},
    ])
    result = parse_enrichment(text, "Apertura di bergamotto. Iris e legni.", [], ingest.KNOWN_FAMILIES)
    assert [note["position"] for note in result["notes"]] == [None, "top"]


def test_ambiguous_quote_does_not_assign_a_stage():
    text = response([{"name": "Iris", "position": "top", "evidence": "Testa bergamotto, cuore iris"}])
    result = parse_enrichment(text, "Testa bergamotto, cuore iris", [], ingest.KNOWN_FAMILIES)
    assert result["notes"][0]["position"] is None


def test_family_inference_and_tag_evidence_are_distinct():
    inferred = {"name": "Legnosa", "kind": "inferred", "evidence": "legni e sandalo"}
    result = parse_enrichment(response(family=inferred), "legni e sandalo", [], ingest.KNOWN_FAMILIES)
    assert result["family"]["kind"] == "inferred"
    explicit = {"name": "Floreale", "kind": "explicit", "evidence": "Floreale"}
    result = parse_enrichment(response(family=explicit), "", ["Floreale"], ingest.KNOWN_FAMILIES)
    assert result["family"]["source"] == "tags"
    assert parse_enrichment(response(family=explicit), "Legni", [], ingest.KNOWN_FAMILIES)["family"] is None


@pytest.mark.parametrize("text", ["[ID: PRODOTTO_1]", "{}", '{"notes":"Iris","family":null}'])
def test_invalid_enrichment_envelope_is_rejected(text):
    with pytest.raises(ValueError):
        parse_enrichment(text, "Iris", [], ingest.KNOWN_FAMILIES)


def test_llm_receives_tags_and_original_data_without_revealing_reasoning():
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=response(), reasoning_content="Privato"), finish_reason="stop")])
    result = enrich_catalog_fields(client, "Test", "Brand", "Iris e legni", ["Unisex"],
                                  {"top": ["Bergamotto"], "heart": [], "base": []}, "", ingest.KNOWN_FAMILIES)
    context = json.loads(client.chat.completions.create.call_args.kwargs["messages"][1]["content"])
    assert context["tags"] == ["Unisex"]
    assert context["existing_pyramid"]["top"] == ["Bergamotto"]
    assert result == {"notes": [], "family": None, "successful": True}
    assert client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "low"
    assert client.chat.completions.create.call_args.kwargs["max_tokens"] == 2048


def test_complete_data_and_missing_client_skip_external_calls():
    client = MagicMock()
    pyramid = {"top": ["Limone"], "heart": ["Iris"], "base": ["Sandalo"]}
    assert enrich_catalog_fields(client, "T", "B", "Testo", [], pyramid, "Legnosa", []) == {"notes": [], "family": None}
    client.chat.completions.create.assert_not_called()
    assert enrich_catalog_fields(None, "T", "B", "Testo", [], {}, "", []) == {"notes": [], "family": None}


def test_transform_preserves_existing_fields_and_uses_grounded_missing_data(monkeypatch):
    parsed = {"top": ["Bergamotto"], "heart": [], "base": [], "family": "Agrumata",
              "ptype": "EDP", "usage_profile": "Uso diurno", "description": "Iris e sandalo"}
    monkeypatch.setattr(ingest, "parse_shopify_sections", lambda text: parsed)
    monkeypatch.setattr(ingest, "extract_pyramid_regex_fallback", lambda text: {"top": [], "heart": [], "base": []})
    monkeypatch.setattr(ingest, "_get_groq_client", lambda: None)
    recovered = {"notes": [
        {"name": "Limone", "position": "top", "source": "description", "evidence": "Apertura limone"},
        {"name": "Iris", "position": None, "source": "description", "evidence": "Iris e sandalo"},
        {"name": "Sandalo", "position": "base", "source": "description", "evidence": "Fondo sandalo"}],
        "family": {"value": "Legnosa", "kind": "inferred", "source": "description", "evidence": "sandalo"}}
    monkeypatch.setattr(ingest, "enrich_catalog_fields", lambda *args: recovered)
    product = ingest.transform_product({"id": 1, "title": "Test", "handle": "test", "tags": [],
        "body_html": "Iris e sandalo", "variants": [{"id": 2, "price": "90", "available": True}]}, "https://example.com")
    assert product["olfactory_pyramid"] == {"top": ["Bergamotto"], "heart": [], "base": ["Sandalo"]}
    assert product["unpositioned_notes"] == ["Iris"]
    assert product["family"] == "Agrumata"
    assert product["family_inference"] is None
    assert product["data_provenance"]["pyramid"]["top"]["source"] == "html"
    assert "floreali/speziate" not in product["semantic_text"]
    assert "Note di cuore" not in product["semantic_text"]


def test_inferred_family_is_separate_and_no_generic_notes_are_added(monkeypatch):
    monkeypatch.setattr(ingest, "_get_groq_client", lambda: None)
    monkeypatch.setattr(ingest, "enrich_catalog_fields", lambda *args: {"notes": [], "family": {
        "value": "Legnosa", "kind": "inferred", "source": "description", "evidence": "legni"}})
    product = ingest.transform_product({"id": 1, "title": "Test", "handle": "test", "tags": [],
        "body_html": "Una composizione di legni", "variants": [{"id": 2, "price": "90", "available": True}]}, "https://example.com")
    assert product["family"] == ""
    assert product["family_inference"]["value"] == "Legnosa"
    assert "dedotta" in product["semantic_text"]
    assert "Note di testa" not in product["semantic_text"]
    assert "fresche/agrumate" not in product["semantic_text"]


def test_successful_enrichment_is_reused_without_another_call(monkeypatch):
    raw = {"id": 1, "title": "Test", "handle": "test", "tags": [],
           "body_html": "Una composizione di iris", "variants": [{"id": 2, "price": "90", "available": True}]}
    recovered = {"notes": [{"name": "Iris", "position": None, "source": "description",
                            "evidence": "composizione di iris"}], "family": None, "successful": True}
    llm = MagicMock(return_value=recovered)
    monkeypatch.setattr(ingest, "_get_groq_client", lambda: None)
    monkeypatch.setattr(ingest, "enrich_catalog_fields", llm)
    first = ingest.transform_product(raw, "https://example.com")
    batch = ingest.EnrichmentBatch()
    second = ingest.transform_product(raw, "https://example.com", first, batch)
    assert llm.call_count == 1
    assert second["unpositioned_notes"] == ["Iris"]
    assert batch.cached == 1
    # Price changes do not invalidate extraction; description changes do.
    raw["variants"][0]["price"] = "100"
    ingest.transform_product(raw, "https://example.com", first)
    assert llm.call_count == 1
    raw["body_html"] = "Una composizione di iris e sandalo"
    ingest.transform_product(raw, "https://example.com", first)
    assert llm.call_count == 2


def test_failed_enrichment_is_not_cached(monkeypatch):
    raw = {"id": 1, "title": "Test", "handle": "test", "tags": [],
           "body_html": "Una composizione di iris", "variants": [{"id": 2, "price": "90", "available": True}]}
    monkeypatch.setattr(ingest, "_get_groq_client", lambda: None)
    llm = MagicMock(return_value={"notes": [], "family": None, "successful": False})
    monkeypatch.setattr(ingest, "enrich_catalog_fields", llm)
    first = ingest.transform_product(raw, "https://example.com")
    assert first["enrichment_cache"] is None
    ingest.transform_product(raw, "https://example.com", first)
    assert llm.call_count == 2


def test_long_quota_wait_suspends_batch_without_sleeping(monkeypatch):
    from src import catalog_enrichment as enrichment
    batch = enrichment.EnrichmentBatch()
    sleep = MagicMock()
    monkeypatch.setattr(enrichment.time, "sleep", sleep)
    assert batch.before_request()
    batch.on_failure("rate_limit", 3600)
    batch.after_request(False)
    assert batch.suspended
    assert not batch.before_request()
    sleep.assert_not_called()


def test_short_quota_cooldown_and_failure_circuit(monkeypatch):
    from src import catalog_enrichment as enrichment
    monkeypatch.setenv("GROQ_CATALOG_INTERVAL_SECONDS", "2")
    monkeypatch.setattr(enrichment.time, "monotonic", lambda: 100)
    sleep = MagicMock()
    monkeypatch.setattr(enrichment.time, "sleep", sleep)
    batch = enrichment.EnrichmentBatch()
    for number in range(3):
        assert batch.before_request()
        batch.on_failure("rate_limit", 12)
        batch.after_request(False)
    assert sleep.call_args.args == (12,)
    assert batch.failed == 3
    assert batch.suspended


def test_success_resets_failure_count(monkeypatch):
    from src.catalog_enrichment import EnrichmentBatch
    batch = EnrichmentBatch()
    batch.on_failure("timeout", None)
    batch.after_request(False)
    batch.after_request(True)
    assert batch.consecutive_failures == 0
    assert not batch.suspended
