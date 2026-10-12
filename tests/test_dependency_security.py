"""Security policies must fail closed without contacting advisory services."""
import copy
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.chroma_security import validate_local_embedding
from tools.security.audit import evaluate

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 12)


def policy():
    return json.loads((ROOT / "tools/security/exceptions.json").read_text())


def report(identifier="CVE-2026-45829", name="chromadb", version="1.5.9", fixes=None):
    return {"dependencies": [{"name": name, "version": version, "vulns": [{
        "id": identifier, "aliases": [], "fix_versions": fixes or []}]}]}


@pytest.mark.parametrize("entry", policy()["exceptions"])
def test_known_chroma_findings_remain_visible_as_temporary_mitigations(entry):
    result = evaluate(report(entry["ids"][0]), policy(), TODAY)
    assert result["unaccepted"] == []
    assert result["mitigated"][0]["reason"]
    assert result["mitigated"][0]["expires"] == "2026-11-12"


@pytest.mark.parametrize("changed", [report("NEW-ADVISORY"), report(name="other"),
                                      report(version="1.5.8"), report(fixes=["1.5.10"])])
def test_new_findings_versions_packages_and_available_fixes_are_not_waived(changed):
    result = evaluate(changed, policy(), TODAY)
    assert result["unaccepted"]
    assert not result["mitigated"]


def test_aliases_match_only_documented_advisory():
    item = report("PYSEC-simulated")
    item["dependencies"][0]["vulns"][0]["aliases"] = ["CVE-2026-45829"]
    assert evaluate(item, policy(), TODAY)["mitigated"]


def test_expired_exception_fails_even_if_not_reported_and_skipped_packages_fail():
    empty = {"dependencies": [{"name": "test", "version": "1", "vulns": []}]}
    with pytest.raises(ValueError, match="Expired"):
        evaluate(empty, policy(), date(2026, 11, 12))
    empty["dependencies"][0]["skip_reason"] = "not found"
    assert evaluate(empty, policy(), TODAY)["unaccepted"]


@pytest.mark.parametrize("broken", [{}, {"dependencies": []}, {"dependencies": None}])
def test_missing_or_empty_audit_report_never_passes(broken):
    with pytest.raises((ValueError, KeyError)):
        evaluate(broken, policy(), TODAY)


def collection(name="default", parameters=None, schema=None):
    return SimpleNamespace(configuration_json={"embedding_function": {
        "type": "known", "name": name, "config": parameters or {}}},
        _model=SimpleNamespace(serialized_schema=schema))


@pytest.mark.parametrize("name,params", [("default", {}), ("onnx_mini_lm_l6_v2", {}),
                                       ("onnx_mini_lm_l6_v2", {"preferred_providers": ["CPUExecutionProvider"]})])
def test_only_fixed_local_embeddings_are_allowed(name, params):
    validate_local_embedding(collection(name, params))


def test_standard_nested_schema_and_unused_sparse_placeholder_are_safe():
    schema = {"defaults": {"embedding_function": {"type": "known", "name": "default", "config": {}}},
              "sparse": {"embedding_function": {"type": "unknown"}}}
    validate_local_embedding(collection(schema=schema))


@pytest.mark.parametrize("bad", [collection("sentence_transformer", {"trust_remote_code": True}),
    collection("default", {"trust_remote_code": True}), collection("default", {"model_name": "remote"}),
    collection("onnx_mini_lm_l6_v2", {"preferred_providers": ["CustomProvider"]}),
    collection(schema={"embedding_function": {"name": "remote"}})])
def test_remote_or_alternative_schema_is_rejected_before_deserialization(bad):
    with pytest.raises(RuntimeError, match="non autorizzata"):
        validate_local_embedding(bad)


def test_security_workflow_has_schedule_reports_and_no_secrets_or_automatic_fixes():
    text = (ROOT / ".github/workflows/security.yml").read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["on"]["schedule"]
    assert "secrets." not in text and "--fix" not in text
    assert 'tools/security/audit.py --output' in text
    assert 'npm audit --package-lock-only --ignore-scripts' in text
    for job in workflow["jobs"].values():
        assert int(job["timeout-minutes"]) <= 15
        upload = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-artifact@"))
        assert upload["if"] == "always()"
        assert upload["with"]["if-no-files-found"] == "error"


def test_security_tools_are_isolated_and_uv_correction_is_pinned():
    runtime = (ROOT / "requirements.txt").read_text()
    development = (ROOT / "requirements/dev.txt").read_text()
    assert "uv==0.11.15" in development
    assert "uv==" not in runtime and "pip-audit==" not in runtime
    assert "pip-audit==2.10.1" in (ROOT / "requirements/security.txt").read_text()
