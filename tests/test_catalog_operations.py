"""Catalog reports, freshness, Rome dates and commercial rules without services."""
from datetime import date, datetime, timedelta, timezone
import io
import zipfile
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.request import Request

import pytest
import yaml
from fastapi.testclient import TestClient

from src.catalog_operations import catalog_kind, requested_scope, quality, sync_report
from src import ingest
from tools.catalog.operations import alternating_day, freshness, SafeRedirect
import tools.catalog.operations as operations
from tests.test_recommendation_preferences import product, advisor_for
from src.recommendation_preferences import PreferenceMatcher
import src.main as api

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name,price,expected", [("KITE IN CRYSTAL REEF", 180, "perfume"),
    ("Discovery Set Frassai", 65, "kit"), ("Discovery Kit", 45, "kit"), ("Not a perfume", 0, "gift")])
def test_commercial_classification_uses_whole_words(name, price, expected):
    assert catalog_kind(product(name=name, price=price)) == expected


def test_ordinary_and_kit_recommendations_are_separate_and_gifts_never_automatic():
    products = [product("normal"), product("kit", name="Discovery Kit"), product("gift", price=0)]
    matcher = PreferenceMatcher(products)
    assert [p["id"] for p in matcher.select({})[0]] == ["normal"]
    prefs = matcher.update("Cerco un kit")
    assert [p["id"] for p in matcher.select(prefs)[0]] == ["kit"]
    assert matcher.update("più economico", prefs)["catalog_scope"] == "kit"
    assert matcher.update("cerco un profumo", prefs)["catalog_scope"] == "perfume"
    assert requested_scope("non voglio un kit") == "perfume"


def test_named_kit_recommendation_retains_scope_after_name_erasure(tmp_path):
    advisor = advisor_for(tmp_path, [product("normal"), product("kit", name="Discovery Kit")])
    reply = advisor.advise("Consigliami Discovery Kit", "customer", session_key="b" * 64)
    assert reply["products"][0]["id"] == "kit"


def test_missing_information_is_counted_and_inferred_families_remain_valid():
    item = product(notes=[], family="", family_inference={"value": "Legnosa"})
    stats = quality([item])
    assert stats["missing_family"] == 0
    assert stats["missing_notes"] == 1
    assert stats["incomplete_pyramid"] == 1


def test_report_detects_price_stock_added_removed_and_large_count_changes(tmp_path):
    previous = [product(str(i)) for i in range(10)]
    current = [dict(previous[0], price=75), product("new")]
    unavailable = [dict(previous[1], in_stock=False)]
    report = sync_report(current, unavailable, 4, previous, tmp_path)
    assert report["changes"] == {"added": 1, "removed": 8, "price_changed": 1, "stock_changed": 1}
    assert report["warnings"]
    assert report["status"] == "success"
    assert report["catalog_hash"]


def test_unchanged_import_is_verified_without_changing_product_data(tmp_path):
    items = [product()]
    first = sync_report(items, [], 0, items, tmp_path, datetime(2026, 10, 13, tzinfo=timezone.utc))
    second = sync_report(items, [], 0, items, tmp_path, datetime(2026, 10, 15, tzinfo=timezone.utc))
    assert first["catalog_hash"] == second["catalog_hash"]
    assert first["verified_at"] != second["verified_at"]
    assert not any(second["changes"].values())


def test_failure_report_does_not_claim_success_or_overwrite_catalog(tmp_path, monkeypatch):
    target = tmp_path / "catalog.json"
    target.write_text('[{"id":"previous"}]')
    monkeypatch.setattr(ingest, "OUTPUT_FILE", target)
    monkeypatch.setattr(ingest, "_run_ingest", MagicMock(side_effect=RuntimeError("private error")))
    with pytest.raises(RuntimeError):
        ingest.run_ingest()
    report = json.loads((tmp_path / "catalog_sync_report.json").read_text())
    assert report["status"] == "failed" and "verified_at" not in report
    assert "private error" not in json.dumps(report)
    assert target.read_text() == '[{"id":"previous"}]'


def test_alternation_spans_months_and_dst_dates_without_reset():
    anchor = date(2026, 10, 13)
    for offset in range(220):
        assert alternating_day(anchor + timedelta(days=offset)) == (offset % 2 == 0)


@pytest.mark.parametrize("hours,stale", [(0, False), (48, False), (72, False), (73, True)])
def test_freshness_uses_verified_import_time(hours, stale):
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    report = {"version": 1, "status": "success", "catalog_hash": "a" * 64,
              "verified_at": (now - timedelta(hours=hours)).isoformat()}
    assert freshness(report, now)["stale"] == stale
    for bad in [{**report, "status": "failed"}, {**report, "catalog_hash": "bad"},
                {**report, "verified_at": "2026-10-16T00:00:00"}]:
        with pytest.raises(ValueError):
            freshness(bad, now)


def test_artifact_redirect_drops_token_and_rejects_plain_http():
    req = Request("https://api.github.com/example", headers={"Authorization": "Bearer private"})
    headers = {}
    redirected = SafeRedirect().redirect_request(req, None, 302, "", headers, "https://artifacts.example/report")
    assert not redirected.has_header("Authorization")
    with pytest.raises(ValueError):
        SafeRedirect().redirect_request(req, None, 302, "", headers, "http://artifacts.example/report")


def test_latest_successful_artifact_is_read_in_memory_without_extraction(monkeypatch):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("catalog_sync_report.json", json.dumps({"version": 1, "status": "success"}))
    replies = [json.dumps({"workflow_runs": [{"id": 7}]}).encode(),
               json.dumps({"artifacts": [{"id": 9, "name": "catalog-sync-report", "expired": False}]}).encode(),
               payload.getvalue()]
    opener = SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(replies.pop(0)))
    monkeypatch.setattr(operations, "build_opener", lambda *args: opener)
    assert operations.latest_report("owner/repository", "dummy") == {"version": 1, "status": "success"}
    assert not replies


def test_missing_report_fails_monitor_and_manual_sync_bypasses_alternation(tmp_path, monkeypatch):
    opener = SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(b'{"workflow_runs":[]}'))
    monkeypatch.setattr(operations, "build_opener", lambda *args: opener)
    with pytest.raises(ValueError, match="No successful"):
        operations.latest_report("owner/repo", "dummy")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(operations.sys, "argv", ["operations.py", "schedule"])
    operations.main()
    assert output.read_text().strip() == "run=true"


def test_summary_is_operator_visible_and_reports_are_not_tracked(tmp_path, monkeypatch):
    from src.catalog_operations import write_report
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    write_report(tmp_path / "report.json", {"quality": {"products": 3}})
    assert '"products": 3' in summary.read_text()
    ignored = (ROOT / ".gitignore").read_text()
    assert "data/catalog_sync_report.json" in ignored
    assert "data/catalog_enrichment_report.json" in ignored


def test_workflows_use_rome_reports_and_preserve_shared_write_lock():
    for filename, cron in [("catalog-sync.yml", "0 2 * * *"), ("catalog-enrich.yml", "35 2 * * *")]:
        text = (ROOT / ".github/workflows" / filename).read_text()
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
        assert workflow["on"]["schedule"][0] == {"cron": cron, "timezone": "Europe/Rome"}
        assert workflow["concurrency"]["group"] == "catalog-maintenance-feature-new-site"
        assert "actions/upload-artifact@v4" in text
        if filename == "catalog-sync.yml":
            assert "operations.py schedule" in text
            assert 'git add data/catalog.json data/out_of_stock.json data/catalog_enrichment_state.json' in text
            assert "git add data/catalog_sync_report.json" not in text


def test_status_is_operational_and_does_not_replace_health(monkeypatch):
    engine = SimpleNamespace(manifest={"generation": "a" * 32, "created_at": "2026-10-12T00:00:00Z", "product_count": 1},
        catalog_quality={"products": 1}, source_matches_active=False)
    monkeypatch.setattr(api, "advisor", SimpleNamespace(search_engine=engine))
    client = TestClient(api.app)
    response = client.get("/catalog/status")
    assert response.status_code == 200
    assert response.json()["source_matches_active_at_startup"] is False
    assert "sync_verification" in response.json()
    assert client.get("/health").status_code == 200
