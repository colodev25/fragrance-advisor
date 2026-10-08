# Dependency and test maintenance

## File organization

`requirements/` groups Python inputs and the development/catalog locks. The runtime `requirements.txt` stays at the repository root for the existing Render build command. `tools/widget-tests/` contains the npm manifest and lock used only for browser checks. Test implementations remain under `tests/`; runtime version files remain at the root. Run the commands below from the repository root.

## Reproducible installations

Use Python 3.11 (`.python-version`) and Node 24.19.0 (`.node-version`). Render reads `.python-version`; a dashboard `PYTHON_VERSION` setting takes precedence and must agree with the selected Python series. The existing Render build and start commands remain valid.

| File | Purpose |
| --- | --- |
| `requirements/runtime.in` → `requirements.txt` | Direct runtime dependencies and generated exact versions, including indirect dependencies. Used by Render. |
| `requirements/dev.in` → `requirements/dev.txt` | Runtime plus pytest and the lock-generation tool. Used by Python CI and local checks. |
| `requirements/catalog.in` → `requirements/catalog.txt` | Minimal catalog-job dependencies, constrained to runtime versions. Used by synchronization and enrichment workflows. |
| `tools/widget-tests/package.json` + `tools/widget-tests/package-lock.json` | Browser-test scripts and exact Playwright dependency tree, with npm integrity records. |

Install the appropriate generated `.txt` file; `.in` files are inputs for maintainers. Python locks are generated with platform markers for Windows/Linux and Python 3.11 compatibility. They fix package versions, not artifact hashes or operating-system libraries. Use a fresh environment when reproducing an installation; installing into an existing environment can leave unrelated packages behind.

## Updating Python packages

1. Create an isolated Python 3.11 environment and install `requirements/dev.txt`.
2. Change the relevant direct version in `requirements/runtime.in` or `requirements/dev.in`.
3. Regenerate all three files in order with uv 0.9.9:

```sh
uv pip compile requirements/runtime.in --universal --python-version 3.11 --no-annotate -o requirements.txt
uv pip compile requirements/dev.in -c requirements.txt --universal --python-version 3.11 --no-annotate -o requirements/dev.txt
uv pip compile requirements/catalog.in --universal --python-version 3.11 --no-annotate -o requirements/catalog.txt
```

Use `--upgrade-package PACKAGE` to deliberately update an indirect dependency; ordinary compilation prefers existing locked versions. Install the regenerated development lock in a fresh environment, check compatibility and run the [offline suites](TESTING.md). Review both source and generated changes before committing. Avoid unreviewed bulk upgrades.

## Updating browser tools

Change the exact Playwright version in `tools/widget-tests/package.json`, then regenerate and install its lock:

```sh
npm --prefix tools/widget-tests install --package-lock-only --ignore-scripts --no-audit --no-fund
npm --prefix tools/widget-tests ci --ignore-scripts --no-audit --no-fund
npm --prefix tools/widget-tests run browser:install
npm --prefix tools/widget-tests run test:widget
```

The browser suite resolves Playwright from this tools directory; an explicit `WIDGET_PLAYWRIGHT_MODULE` still supports an external installation. Review widget geometry, navigation and security failures rather than hiding them with automatic retries. The three widget source files remain maintained individually for now.

## Before publishing

- Run the Python and browser checks described in [TESTING.md](TESTING.md).
- Commit the generated dependency locks together with their inputs and workflow changes.
- Check both GitHub test jobs after pushing. A local passing run does not establish that remote CI or Render deployment passed.
- Updating the installed Shopify snippet remains a separate publishing step when widget sources change.
- Schedule dependency reviews periodically, and sooner when an upstream fix affects the project. Fixed versions still need deliberate maintenance.

## References

The workflow follows the documented approaches for [repeatable pip installations](https://pip.pypa.io/en/stable/topics/repeatable-installs/), [uv compilation](https://docs.astral.sh/uv/pip/compile/), [Playwright CI](https://playwright.dev/docs/ci) and [Render Python version selection](https://render.com/docs/python-version).
