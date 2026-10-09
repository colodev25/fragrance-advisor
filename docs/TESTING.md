# Testing

The project uses pytest. Tests cover the HTTP API, catalog parsing and advisor rules, session persistence, LLM retry behavior, and end-to-end recommendation scenarios.

## Test files

| File | Coverage |
| --- | --- |
| tests/test_api.py | Health check, chat and reset routes, response shape, request validation and CORS preflight. |
| tests/test_parsers.py | Note cleaning, note extraction, gender and season detection, price constraints, intent routing and guided-flow steps. |
| tests/test_session_store.py | SQLite defaults, save and load, updates, clearing, concurrent writes, restart persistence and reset through the API. |
| tests/test_conversation_requests.py | Per-session serialization, independent customers, concurrent duplicates, reset during processing, atomic state/result commits, restart recovery, identifier conflicts, response pruning, schema migration and HTTP retry contracts. Uses temporary SQLite databases and mocked processing without constructing external clients. |
| tests/test_session_access.py | Mandatory credentials, ownership before continuation/replay/reset, atomic first claims, first-response recovery, omitted contexts, legacy-session refusal and hashed-only storage. Uses the real API and SQLite with mocked processing. |
| tests/test_session_lifecycle.py | 24-hour inactivity expiry, renewal and replay rules, lost databases, tokens and stale revisions, cleanup batching and busy-session safety, migration, connection closure, RAM release, product-ID refresh, removed stock and API validation. No external services. |
| tests/test_recommendation_preferences.py | Note polarity, English aliases, compound notes, AND/OR requests, conservative exclusions, unknown constraints, exact/partial matches, required preferences, price boundaries and API ceilings, persistent profiles, guided clarification, named references, stable card IDs and catalog-wide admission. No external services. |
| tests/test_product_cards.py | Complete pyramid details, separate unpositioned notes, accent/case deduplication, declared notes in multiple stages, bounded summaries, missing notes, legacy catalogs, clean concentration/recipient labels and internal versus displayed season evidence. No model or search client is constructed. |
| tests/test_chat_budget.py | Shared deadlines and call allowance, SDK retries disabled using an in-memory transport, fast replies without added waits, reduced timeouts, completion ceilings, short and long provider cooldowns, failed-state rollback, guided-card fallback and retryable HTTP errors. No external services. |
| tests/test_llm_resilience.py | Retry delays, fallback model, concurrent calls, private reasoning protection, truncated answers, candidate selection validation, graceful failure and an optional live Groq check. |
| tests/test_rate_limit.py | Per-client and per-route request limits. |
| tests/test_offline_policy.py | Dummy credentials, isolated session database, blocked external DNS/IP connections and allowed local loopback. |
| tests/test_maintenance_config.py | Exact dependency versions, shared runtime/catalog/dev pins, npm lock consistency and offline CI discovery/browser jobs. |
| tests/test_catalog_integrity.py | Catalog validation, atomic writes, generation activation, failed builds, removed products and interrupted ingestion, without external services. |
| tests/test_catalog_enrichment.py | Source evidence, partial merges, unpositioned notes, explicit versus inferred families, cache reuse/invalidation, quota cooldowns, failure suspension, generic-note removal and olfactory versus promotional salt tags, without external calls. |
| tests/test_catalog_jobs.py | Synchronization without Groq, stock transitions, queue lifecycle, empty results, deferred retries and persistent token reservations, using temporary datasets and mocked clients. |
| tests/test_widget_security.cjs | Real-browser checks for the standalone widget, Shopify snippet and local DevTools preview when present: safe rendering, navigation, restored actions, concurrent sends, duplicate retries, message identity, pending-request recovery, retired retries and late responses after reset. Timeouts, numeric/date cooldowns, navigation during cooldown and preview reinsertion are covered. All network requests are intercepted. |
| tests/test_scenarios_e2e.py | Full advisor scenarios for note and season requests, product follow-ups, cheaper alternatives, unsupported requests and guided recommendations. |

## Run tests

Use Python 3.11 (`.python-version`) and install the pinned test dependencies:

    python -m pip install -r requirements/dev.txt
    python src/reindex.py
    python -m pytest tests -m "not e2e"

Index preparation uses the local catalog and can download the public embedding model on its first run. It does not call Groq or Shopify. If a verified index already exists, rebuilding it is unnecessary for normal test runs.

Run a single test module with:

    pytest tests/test_api.py
    pytest tests/test_session_store.py

Tests are offline by default, including plain `pytest`: `tests/conftest.py` supplies a dummy Groq credential, puts the application database under pytest's temporary directory and blocks external DNS resolution and socket connections. Loopback remains available for the HTTP test client. Model/search transports used by individual tests are mocked as needed. The ordinary suite still exercises the existing local search index.

Real Groq tests require an explicit opt-in, a real key and the catalog/index:

    python -m pytest tests --live-services -m e2e

This option disables the offline network and credential policy and can consume quota. It is not used in CI. The `e2e` marker is registered in `pytest.ini`; without `--live-services`, marked tests are skipped even if a real key is present in `.env`.

`SessionStore` uses a new, closed connection for each operation. Plain SQLite `:memory:` would lose its schema between operations and is therefore rejected with an explicit error, whether supplied directly or through `SESSIONS_DB_PATH`. Use a temporary database file, as the fixtures and CI do; these tests include concurrent writes and restart recovery.

## Continuous integration

.github/workflows/tests.yml runs two independent jobs on pushes and pull requests to `feature/new-site` or `main`, plus manual dispatch:

- **Python:** installs `requirements/dev.txt`, checks dependency compatibility, prepares the local index and discovers all Python tests under `tests/`, excluding `e2e`. This includes rate-limit and future test modules without maintaining a filename list. The session database and test files are under the runner's temporary directory.
- **Browser:** uses the Node version in `.node-version`, installs from `tools/widget-tests/package-lock.json` with `npm --prefix tools/widget-tests ci`, installs Chromium and runs `npm --prefix tools/widget-tests run test:widget`. This checks the two tracked widget variants; the ignored DevTools preview is tested locally when present.

Neither test job needs Groq or Shopify secrets. Dependency/browser/model installation can access public download servers; test calls to external services are blocked. Each job has a 15-minute ceiling and the workflow has read-only repository permissions. These are test jobs; Render's automatic deploy remains separately configured.

## Widget browser checks

The JavaScript suite uses Node.js 24 and pinned Playwright with a Chromium-based browser. It runs the actual scripts from `index.html` and `snippets/etualy-advisor.liquid`, plus the ignored local `snippet.txt` when available. A fresh clone without that preview still runs the two tracked widget variants; only preview-specific coverage is skipped. Test-only hooks are injected in memory; the production files do not expose them. The HTML fixture is served as UTF-8, as required by the storefront document.

```sh
npm --prefix tools/widget-tests ci --ignore-scripts --no-audit --no-fund
npm --prefix tools/widget-tests run browser:install
npm --prefix tools/widget-tests run test:widget
```

Playwright must be resolvable by Node. If using an existing runtime rather than a project installation, set `WIDGET_PLAYWRIGHT_MODULE` to its Playwright package directory. Set `WIDGET_BROWSER_EXECUTABLE` to an installed Chromium, Chrome or Edge executable; otherwise Playwright uses its installed Chromium. These variables are for tests only. The local verification used Playwright 1.62.1 and headless Edge.

All page requests are intercepted: HTML, API responses and a sample image are supplied locally; other requests are blocked. No Groq key, Shopify access or running backend is required. Browser contexts and temporary profiles close after the run. The local suite contains 165 checks with the DevTools preview; a clean clone runs 110 checks on the two tracked variants. Browser tests now have a separate job in the same CI workflow.

Card-detail checks cover both card types, complete and partial pyramids, separate additional notes, duplicates, missing data, legacy summaries, safe normalization, focus and restored standard-card panels. Profile checks use simulated HTTP responses and old saved history to verify that the type excludes the recipient and the season omits the derivation suffix. Mobile checks verify wrapping, bounded panel height, internal scrolling and reachable close actions. Selected-card checks open the first, middle and last recommendation, then reopen the first, on desktop and mobile (including a short viewport and reduced motion). They verify that the expanded card remains inside the message viewport, long notes scroll internally and the host page does not scroll. Setting the test-only `WIDGET_SCREENSHOT_DIR` saves an example detail-panel screenshot there during the standalone-page check.

Request-coordination checks deliberately deliver both successful and failed responses after cancellation, while a new session is waiting. They also simulate navigation before a response arrives and verify recovery with the original request identifier and a single customer message.

## Latest local verification

After regrouping the files on 8 October 2026, **9 maintenance-configuration tests** passed in the existing local Python environment. Pip successfully parsed all five relocated input/lock files, including relative runtime and constraint references. An offline `npm ci` from the relocated lock succeeded, and `npm --prefix tools/widget-tests run test:widget` passed **165 browser checks** with Node 24.19.0 and headless Edge, without a `WIDGET_PLAYWRIGHT_MODULE` override. This verifies module resolution from the new tools directory. Temporary reports and the test-installed `node_modules` were removed after success; no external provider calls were made. The complete Python suite was not rerun for this file reorganization; its preceding result is recorded below.

On 8 October 2026, the maintenance changes passed **309 Python tests** (6 real-service tests deselected) in a fresh Python 3.11.14 environment installed from `requirements/dev.txt`, plus **165 browser checks** with Node 24.19.0, Playwright installed using the npm lock and headless Edge. A normal run without a marker filter also passed 26 checks and skipped all 6 real-service tests automatically. Dependency checks passed; a Linux/Python 3.11 binary-package resolution succeeded, and a new verified 643-product index was built in a temporary directory with the locked dependencies. These are local checks; Linux execution and remote GitHub/Render outcomes remain to be observed after pushing. The isolated environment, test index and reports were removed after successful verification.

A browser run reproduced the earlier consecutive-card visibility failure. Card toggles now cancel a previous smooth scroll before changing height, and the message area disables automatic browser scroll anchoring. All 12 targeted geometry checks and the subsequent full 165-check run passed after that correction. The three widget variants, including the local DevTools preview, contain the same change.

On 8 October 2026, the subsequent selected-card scrolling correction passed the complete **165-check browser suite** on all three widget variants. The added checks repeatedly opened the first, middle and last card on desktop, mobile and a short mobile viewport, also with reduced motion. No backend code changed and Python tests were not rerun for this UI correction. An initial full run had one mobile visibility timeout; the targeted repeat and the full run with additional open/close cycles passed. Its original cause was not established.

On 8 October 2026, the point-7 changes and profile refinements passed **293 Python tests** and **153 browser checks**, with the live Groq test excluded. Python used dummy credentials, a temporary SQLite file and blocked external socket connections, allowing only local loopback needed by the Windows HTTP test client. API/parser regressions used the existing verified local search index. Browser tests used headless Edge and intercepted every request; virtual clocks exercised deadlines, countdowns and session expiry without real waits.

Coverage includes the real SDK with an in-memory HTTP transport, request/state recovery after LLM failure, catalog enrichment, concurrent sessions and both numeric and HTTP-date `Retry-After`. Session tests also cover loss after deploy, expired replay prevention, stale tabs, pending-message preservation, draft persistence, version-1/version-2 retirement, credential generation and rotation, authorization failures and safe cleanup. Preference checks cover note exclusions and AND/OR requests, unknown constraints, style words, strict and preferred criteria, incomplete catalog evidence, persistent refinements, price conflicts, guided clarification, named references and candidate/card identity. Card tests verify complete catalog details, separate additional notes, missing data and deduplication; enrichment checks distinguish salt tags from explicit promotions and verify selective signature changes. Browser checks exercise the new sections, focus, mobile overflow and restoration on all three widget variants. The product-card module is included in CI; no remote CI run is claimed.

A local timing sample during point 6 used the 643-product catalog and 30 repetitions of preference parsing plus the two admission/ranking passes used by the advisor, with a supplied 40-ID ranking and no search or LLM call. Median duration was **46.7 ms**, maximum **90.0 ms**; evidence preparation at startup took **2.08 seconds** and is reused across messages. These measurements are local observations, not production latency guarantees. They do not measure embedding/search time, LLM latency, free-plan quota availability or Render cold-start duration.

One earlier Windows run encountered a temporary `PermissionError` during a catalog-test file replacement. The isolated test and subsequent full runs passed. The final Python run used temporary files outside OneDrive; the cause of the original access error was not established. On a synchronized checkout, use `--basetemp` and a pytest cache directory outside the synced tree if temporary-file access is unreliable. Verification directories were removed after the successful runs.

## Adding coverage

Choose tests by the behavior being changed: parser and rule tests for extraction logic, API tests for request or response contracts, session-store tests for persistence, and scenario tests for complete advisor flows. Add live-service checks only when an external call is required; keep deterministic behavior covered with mocks.
