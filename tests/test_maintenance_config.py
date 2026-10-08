"""Keep dependency locks and offline CI contracts consistent without network access."""
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def pins(filename):
    result = {}
    for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        match = re.fullmatch(r"([\w.-]+)(?:\[[\w,.-]+\])?==([^\s;]+)(?:\s*;.*)?", line)
        assert match, f"Unpinned requirement in {filename}: {line}"
        name = match[1].lower().replace("_", "-")
        assert name not in result or result[name] == match[2]
        result[name] = match[2]
    return result


@pytest.mark.parametrize("filename", ["requirements.txt", "requirements/dev.txt", "requirements/catalog.txt"])
def test_generated_requirements_pin_every_package(filename):
    assert pins(filename)


def test_runtime_development_and_catalog_share_versions():
    runtime = pins("requirements.txt")
    development = pins("requirements/dev.txt")
    catalog = pins("requirements/catalog.txt")
    assert all(development.get(name) == version for name, version in runtime.items())
    assert all(runtime.get(name) == version for name, version in catalog.items())
    assert "chromadb" not in catalog and "numpy" not in catalog


def test_direct_runtime_dependencies_match_generated_lock():
    runtime = pins("requirements.txt")
    assert all(runtime.get(name) == version for name, version in pins("requirements/runtime.in").items())


def test_browser_lock_matches_manifest_and_runtime():
    manifest = json.loads((ROOT / "tools/widget-tests/package.json").read_text())
    lock = json.loads((ROOT / "tools/widget-tests/package-lock.json").read_text())
    assert manifest["devDependencies"] == lock["packages"][""]["devDependencies"]
    assert manifest["engines"] == lock["packages"][""]["engines"]
    assert lock["packages"]["node_modules/playwright"]["version"] == manifest["devDependencies"]["playwright"]
    assert lock["packages"]["node_modules/playwright"]["integrity"].startswith("sha512-")
    assert (ROOT / ".node-version").read_text().strip().startswith("24.")
    browser_directory = ROOT / "tools/widget-tests"
    assert "../../tests/test_widget_security.cjs" in manifest["scripts"]["test:widget"]
    assert (browser_directory / "../../tests/test_widget_security.cjs").resolve().is_file()


def test_ci_discovers_all_offline_tests_and_runs_browser_checks():
    path = ROOT / ".github/workflows/tests.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert "secrets." not in text
    commands = "\n".join(step.get("run", "") for step in workflow["jobs"]["run-tests"]["steps"])
    assert 'pytest tests -m "not e2e"' in commands
    assert "requirements/dev.txt" in commands
    browser_commands = "\n".join(step.get("run", "") for step in workflow["jobs"]["widget-tests"]["steps"])
    assert "npm ci" in browser_commands and "npm run test:widget" in browser_commands
    for step in workflow["jobs"]["widget-tests"]["steps"]:
        if "run" in step:
            assert step["working-directory"] == "tools/widget-tests"
    node_setup = next(step for step in workflow["jobs"]["widget-tests"]["steps"]
                      if step.get("uses", "").startswith("actions/setup-node@"))
    assert node_setup["with"]["cache-dependency-path"] == "tools/widget-tests/package-lock.json"


@pytest.mark.parametrize("filename", ["catalog-sync.yml", "catalog-enrich.yml"])
def test_catalog_workflows_install_the_minimal_lock(filename):
    workflow = yaml.load((ROOT / ".github/workflows" / filename).read_text(), Loader=yaml.BaseLoader)
    commands = "\n".join(step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"])
    assert "pip install -r requirements/catalog.txt" in commands
    assert "pip install requests beautifulsoup4" not in commands
