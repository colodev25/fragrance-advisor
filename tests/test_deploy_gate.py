"""Exercise workflow decisions locally, without git pushes or GitHub calls."""
import itertools
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def bash(script, env):
    executable = shutil.which("bash")
    if not executable and os.name == "nt":
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        if candidate.is_file():
            executable = str(candidate)
    if not executable:
        pytest.skip("Bash is required to execute the GitHub runner shell contract")
    result = subprocess.run([executable, "-e", "-o", "pipefail", "-c", script],
                            env=dict(os.environ, **env), capture_output=True, text=True, timeout=15)
    assert result.returncode in (0, 1), "Workflow shell could not execute: " + result.stderr[:2000]
    return result


@pytest.mark.parametrize("python_result,browser_result", list(itertools.product(
    ["success", "failure", "cancelled", "skipped"], repeat=2)))
def test_quality_gate_requires_both_successes(python_result, browser_result):
    gate = workflow("tests.yml")["jobs"]["quality-gate"]
    result = bash(gate["steps"][0]["run"], {
        "PYTHON_RESULT": python_result, "BROWSER_RESULT": browser_result, "GITHUB_SHA": "a" * 40})
    assert (result.returncode == 0) == (python_result == browser_result == "success")


def test_suites_share_commit_and_gate_cannot_skip_failed_dependencies():
    ci = workflow("tests.yml")
    assert "workflow_dispatch" in ci["on"]
    gate = ci["jobs"]["quality-gate"]
    assert gate["needs"] == ["run-tests", "widget-tests"]
    assert gate["if"] == "always()"
    assert gate["steps"][0]["env"] == {
        "PYTHON_RESULT": "${{ needs.run-tests.result }}",
        "BROWSER_RESULT": "${{ needs.widget-tests.result }}"}
    for identifier in gate["needs"]:
        checkout = next(step for step in ci["jobs"][identifier]["steps"]
                        if step.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert ci["permissions"] == {"contents": "read"}


MOCK_GIT = r'''
git() {
  case "$1" in
    status) if [ "$HAS_CHANGES" = true ]; then echo ' M data/catalog_enrichment_state.json'; fi ;;
    diff) if [ "$CATALOG_CHANGED" = true ]; then return 1; fi ;;
    commit) echo "COMMIT: $*" ;;
    push) if [ "$PUSH_FAIL" = true ]; then return 1; fi; echo PUSH ;;
    config|add) return 0 ;;
    *) echo "Unexpected git operation" >&2; return 2 ;;
  esac
}
gh() { echo "DISPATCH: $*"; }
'''


@pytest.mark.parametrize("filename", ["catalog-sync.yml", "catalog-enrich.yml"])
@pytest.mark.parametrize("has_changes,catalog_changed,push_fail", [
    (False, False, False), (True, False, False), (True, True, False), (True, True, True)])
def test_catalog_publication_dispatch_only_after_successful_data_push(
        filename, has_changes, catalog_changed, push_fail, tmp_path):
    ci = workflow(filename)
    steps = next(iter(ci["jobs"].values()))["steps"]
    publish = next(step for step in steps if step.get("id") == "publish")
    dispatch = next(step for step in steps if "gh workflow run" in step.get("run", ""))
    assert ci["permissions"] == {"contents": "write", "actions": "write"}
    assert dispatch["if"] == "always() && steps.publish.outcome == 'success' && steps.publish.outputs.catalog_changed == 'true'"
    assert dispatch["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert 'gh workflow run tests.yml --ref feature/new-site --repo "$GITHUB_REPOSITORY"' == dispatch["run"]
    output = tmp_path / "outputs"
    env = {"HAS_CHANGES": str(has_changes).lower(), "CATALOG_CHANGED": str(catalog_changed).lower(),
           "PUSH_FAIL": str(push_fail).lower(), "GITHUB_OUTPUT": output.as_posix(),
           "GITHUB_REPOSITORY": "example/catalog", "GH_TOKEN": "offline-placeholder"}
    result = bash(MOCK_GIT + publish["run"], env)
    assert (result.returncode != 0) == (has_changes and push_fail)
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    should_dispatch = has_changes and catalog_changed and not push_fail
    assert (values["catalog_changed"] == "true") == should_dispatch
    if has_changes and not catalog_changed:
        assert "[skip render]" in result.stdout
    elif has_changes:
        assert "[skip render]" not in result.stdout
    if should_dispatch:
        dispatched = bash(MOCK_GIT + dispatch["run"], env)
        assert dispatched.returncode == 0
        assert "DISPATCH: workflow run tests.yml --ref feature/new-site --repo example/catalog" in dispatched.stdout
