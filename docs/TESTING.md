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
| tests/test_product_identity.py | Specific and complete names, concentration aliases, brand/size ambiguity, catalog-order independence, every current catalog title through both matching and the real advisor flow, Guidance versus quiz triggers, spelling confirmation, note/name separation, pending choice persistence, budget and alternative intent, removed choices, identical labels, stable active IDs and atomic HTTP retries. No external services. |
| tests/test_chat_budget.py | Shared deadlines and call allowance, SDK retries disabled using an in-memory transport, fast replies without added waits, reduced timeouts, completion ceilings, short and long provider cooldowns, failed-state rollback, guided-card fallback and retryable HTTP errors. No external services. |
| tests/test_llm_resilience.py | Retry delays, fallback model, concurrent calls, private reasoning protection, truncated answers, candidate selection validation, graceful failure and an optional live Groq check. |
| tests/test_rate_limit.py | Per-client and per-route request limits. |
| tests/test_capacity.py | Offline payload/stream limits, unknown fields, admission saturation and worker cancellation, health availability, proxy trust and shared provider call/cooldown budgets. |
| tests/test_offline_policy.py | Dummy credentials, isolated session database, blocked external DNS/IP connections and allowed local loopback. |
| tests/test_maintenance_config.py | Exact dependency versions, shared runtime/catalog/dev pins, npm lock consistency and offline CI discovery/browser jobs. |
| tests/test_catalog_integrity.py | Catalog validation, atomic writes, generation activation, failed builds, removed products and interrupted ingestion, without external services. |
| tests/test_catalog_enrichment.py | Source evidence, partial merges, unpositioned notes, explicit versus inferred families, cache reuse/invalidation, quota cooldowns, failure suspension, generic-note removal and olfactory versus promotional salt tags, without external calls. |
| tests/test_catalog_jobs.py | Synchronization without Groq, stock transitions, queue lifecycle, empty results, deferred retries and persistent token reservations, using temporary datasets and mocked clients. |
| tests/test_narrative_notes.py | Explicit narrative lists, compound materials, source polarity, conservative ambiguity handling, legacy/backlog recovery, model merge, card payloads and validated offline backfill. |
| tests/test_catalog_operations.py | Rome schedules and continuous date alternation, report freshness and failure handling, aggregate quality, commercial scope, artifact retrieval and redirect safety, operational status and workflow contracts. Uses temporary datasets and simulated services. |
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

Dependency vulnerability checks run separately in `.github/workflows/security.yml`, with isolated pinned audit tools, raw artifacts and expiring Chroma exceptions. See [dependency security](DEPENDENCY_SECURITY.md) for scope, commands and limits. `tests/test_dependency_security.py` exercises new/changed findings, available fixes, expiry, missing reports and raw embedding/schema restrictions without external services.

.github/workflows/tests.yml runs two independent jobs on pushes and pull requests to `feature/new-site` or `main`, plus manual dispatch:

- **Python:** installs `requirements/dev.txt`, checks dependency compatibility, prepares the local index and discovers all Python tests under `tests/`, excluding `e2e`. This includes rate-limit and future test modules without maintaining a filename list. The session database and test files are under the runner's temporary directory.
- **Browser:** uses the Node version in `.node-version`, installs from `tools/widget-tests/package-lock.json` with `npm --prefix tools/widget-tests ci`, installs Chromium and runs `npm --prefix tools/widget-tests run test:widget`. This checks the two tracked widget variants; the ignored DevTools preview is tested locally when present.

Neither test job needs Groq or Shopify secrets. Dependency/browser/model installation can access public download servers; test calls to external services are blocked. Each job has a 15-minute ceiling and the workflow has read-only repository permissions. These are test jobs; Render's automatic deploy remains separately configured.

## Widget browser checks

R07 adds offline scenarios for denied storage access/read/write, persistent quota exhaustion, a smaller-history quota retry without clearing storefront keys, overlong draft correction and navigation, deterministic 300 ms draft debouncing, local message/byte limits and restored detail panels on short mobile and landscape viewports. Additional checks protect a focused old product during pruning, recover recent records from older oversized history and preserve oversized drafts in memory without writing an oversized browser state. Storage failures are installed before widget initialization. The debounce scenario freezes browser time to avoid scheduler-dependent assertions. Open cards may shrink below their former outer minimum height so that both the card and its scrollable details fit the conversation viewport.

R05 adds regression checks for hidden/inert controls, keyboard opening and Escape, focus return, mobile focus containment, background inert restoration (including dynamically inserted elements and pre-existing state), desktop/mobile resizing, concise live announcements, neutral text contrast tokens, zoom configuration and doubled text at a 320 px viewport. All three local widget versions are exercised. Browser automation does not replace testing with an actual screen reader, browser zoom, mobile device and the installed Shopify theme.

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

On 13 October 2026, **39 targeted Python checks** passed for catalog operations, the nightly queue and maintenance configuration, including a subsequent passing run after the user's second schedule revision. Workflow assertions validate one daily schedule, valid minute/hour ranges, supported UTC/Rome timezones, manual dispatch and the existing shared write lock/report protections instead of fixed hours/minutes. The final user-defined cron values were preserved: 02:04/02:39/03:17, all with omitted timezone and therefore UTC. External services were simulated. Temporary test directories were removed after success; no full Python or browser run was needed for this schedule/test/documentation change.

On 12 October 2026, cart feedback changes passed **59 distinct targeted browser checks** across all three widgets: a 56-check cart/variant run and a subsequent 15-check error/retry run (12 overlapping checks). Cases verify silent routine success/selection, confirmation after commercial changes, known failures versus uncertain submission, error icon/red colors, safe retry and reduced-motion behavior. Initial checks exposed hover specificity overriding reduced-motion styling; this was corrected. Color checks wait for the existing finite transition before measuring. External services were simulated; backend sources were unchanged and Python/full browser suites were not rerun for this feedback change.

On 12 October 2026, the price/format card layout passed all **300 browser checks** across HTML, Liquid and the local DevTools snippet. New assertions verify a single price below the product header, format-only option buttons, a hidden duplicate format label for multiple options, no redundant single-option selector and a full-width cart action on desktop/mobile. Variant switching, disabled stock, restoration, accessibility and card geometry regressions passed with intercepted external requests. An initial sandboxed run could not launch Edge; the complete run with browser launch permissions passed. Backend sources were unchanged and Python tests were not rerun.

On 12 October 2026, narrative-note recovery passed the final complete offline suite: **514 Python tests**, with **6 live-service tests deselected**, using the existing Python 3.13.15 environment. New cases cover the nine Mirto notes, singular/plural list cues, Italian/English lists, compound materials, source negation and uncertainty, ambiguous marketing/title fragments, partial-pyramid deduplication, preserved local notes during LLM merges, already-completed and unavailable record backfill, card payloads and preview/application validation. The final suite ran after applying local recovery to both real availability datasets; the available catalog's missing-note count fell from 89 to 39. Commercial price, variant and stock fields were checked unchanged. No Shopify/Groq requests were made; the active index was not rebuilt and widget sources were unchanged, so browser tests were not rerun. Temporary verification directories were removed after success. A reindex and backend restart/deploy are required to publish the recovered fields to the widget.

On 12 October 2026, the catalog operations changes passed the complete offline suite: **479 Python tests**, with **6 live-service tests deselected**, using the existing Python 3.13.15 environment. Coverage includes unchanged imports, failed reports, stock/price changes, missing data, kit/gift recommendation rules, alternating Rome dates across month and daylight-saving boundaries, the final 03:00/03:35/04:10 schedules, artifact freshness and operational API responses. Shopify, Groq and GitHub responses were simulated; the real catalog and active index were not modified. Widget sources were unchanged and browser tests were not rerun. The final run passed after aligning schedule assertions with the user's updated workflow times. Temporary test directories were removed after success. Actual GitHub schedules, artifacts and Render deployment still require release checks; scheduled workflows must exist on the default branch and the first successful synchronization initializes monitoring history.

After regrouping the files on 8 October 2026, **9 maintenance-configuration tests** passed in the existing local Python environment. Pip successfully parsed all five relocated input/lock files, including relative runtime and constraint references. An offline `npm ci` from the relocated lock succeeded, and `npm --prefix tools/widget-tests run test:widget` passed **165 browser checks** with Node 24.19.0 and headless Edge, without a `WIDGET_PLAYWRIGHT_MODULE` override. This verifies module resolution from the new tools directory. Temporary reports and the test-installed `node_modules` were removed after success; no external provider calls were made. The complete Python suite was not rerun for this file reorganization; its preceding result is recorded below.

On 8 October 2026, the maintenance changes passed **309 Python tests** (6 real-service tests deselected) in a fresh Python 3.11.14 environment installed from `requirements/dev.txt`, plus **165 browser checks** with Node 24.19.0, Playwright installed using the npm lock and headless Edge. A normal run without a marker filter also passed 26 checks and skipped all 6 real-service tests automatically. Dependency checks passed; a Linux/Python 3.11 binary-package resolution succeeded, and a new verified 643-product index was built in a temporary directory with the locked dependencies. These are local checks; Linux execution and remote GitHub/Render outcomes remain to be observed after pushing. The isolated environment, test index and reports were removed after successful verification.

A browser run reproduced the earlier consecutive-card visibility failure. Card toggles now cancel a previous smooth scroll before changing height, and the message area disables automatic browser scroll anchoring. All 12 targeted geometry checks and the subsequent full 165-check run passed after that correction. The three widget variants, including the local DevTools preview, contain the same change.

On 8 October 2026, the subsequent selected-card scrolling correction passed the complete **165-check browser suite** on all three widget variants. The added checks repeatedly opened the first, middle and last card on desktop, mobile and a short mobile viewport, also with reduced motion. No backend code changed and Python tests were not rerun for this UI correction. An initial full run had one mobile visibility timeout; the targeted repeat and the full run with additional open/close cycles passed. Its original cause was not established.

On 8 October 2026, the point-7 changes and profile refinements passed **293 Python tests** and **153 browser checks**, with the live Groq test excluded. Python used dummy credentials, a temporary SQLite file and blocked external socket connections, allowing only local loopback needed by the Windows HTTP test client. API/parser regressions used the existing verified local search index. Browser tests used headless Edge and intercepted every request; virtual clocks exercised deadlines, countdowns and session expiry without real waits.

Coverage includes the real SDK with an in-memory HTTP transport, request/state recovery after LLM failure, catalog enrichment, concurrent sessions and both numeric and HTTP-date `Retry-After`. Session tests also cover loss after deploy, expired replay prevention, stale tabs, pending-message preservation, draft persistence, version-1/version-2 retirement, credential generation and rotation, authorization failures and safe cleanup. Preference checks cover note exclusions and AND/OR requests, unknown constraints, style words, strict and preferred criteria, incomplete catalog evidence, persistent refinements, price conflicts, guided clarification, named references and candidate/card identity. Card tests verify complete catalog details, separate additional notes, missing data and deduplication; enrichment checks distinguish salt tags from explicit promotions and verify selective signature changes. Browser checks exercise the new sections, focus, mobile overflow and restoration on all three widget variants. The product-card module is included in CI; no remote CI run is claimed.

A local timing sample during point 6 used the 643-product catalog and 30 repetitions of preference parsing plus the two admission/ranking passes used by the advisor, with a supplied 40-ID ranking and no search or LLM call. Median duration was **46.7 ms**, maximum **90.0 ms**; evidence preparation at startup took **2.08 seconds** and is reused across messages. These measurements are local observations, not production latency guarantees. They do not measure embedding/search time, LLM latency, free-plan quota availability or Render cold-start duration.

One earlier Windows run encountered a temporary `PermissionError` during a catalog-test file replacement. The isolated test and subsequent full runs passed. The final Python run used temporary files outside OneDrive; the cause of the original access error was not established. On a synchronized checkout, use `--basetemp` and a pytest cache directory outside the synced tree if temporary-file access is unreliable. Verification directories were removed after the successful runs.

## Adding coverage

### Dependency security — R10 / audit R12 (12 October 2026)

The final complete offline suite passed **458 Python tests**, with **6 live-service tests deselected**, in a fresh Python 3.11.15 environment installed from the updated development lock. Package compatibility passed. A separate temporary generation containing **643 products** was built, loaded through the raw embedding/schema guard and queried successfully; the project's active generation was not rebuilt. The first strict guard rejected Chroma's ordinary generated schema; it was refined to validate nested embedding settings and the unused sparse placeholder before the passing full run.

Audits from the isolated pinned security lock passed policy evaluation: runtime/development retained four distinct Chroma advisories with documented expiring mitigations (the feed emitted five rows because one was duplicated), catalog/security locks had no reported findings, and the widget npm audit reported zero vulnerabilities. The package remains affected; passing policy evaluation is not a clean unmitigated vulnerability scan. Runtime/catalog pins and widget sources were unchanged, so browser tests were not rerun. GitHub execution and Render readiness still require observation after pushing. Temporary verification environments/index/reports were removed after success.

### Response reliability — R09 / audit R11 (11 October 2026)

The final complete browser run passed **300 checks** across HTML, Liquid and the DevTools preview, with every external request intercepted. New checks verify exact HTTPS storefront/CDN allowlists, lookalike domains, ports/credentials, non-clickable model links and navigation restoration; cart and image-failure regressions remain covered. An initial full run had two enlarged-text geometry failures. The test now snapshots all computed font sizes before doubling them, preventing cumulative inherited scaling beyond 200%, and waits for finite transitions before measuring. No production layout change was needed for that test correction. Temporary test directories and logs were removed after the successful final runs.

The final complete offline Python suite passed **434 tests**, with **6 live-service tests deselected**, in the existing local Python 3.13.15 environment. New cases exercise original-source negation (including truncated quotes and tags), hypothetical/comparative note evidence, absence after a note, preserved descriptive negatives, unchanged family inference, cache revalidation and common system policy/structured classifier context. A read-only check of the 21 caches in the current available catalog retained every stored note and all 12 cached families. An initial overly broad clause filter removed valid notes; it was refined before the final passing run. The checks verify prompt construction and deterministic validation; they do not prove the truth of every response from a live model. No Groq/Shopify calls or catalog/index writes were made.

### Capacity protection — R08 / audit R10 (11 October 2026)

The final complete offline Python suite passed **407 tests**, with **6 live-service tests deselected**, using the existing local Python 3.13.15 environment. The 25 capacity regressions cover early body limits, unknown fields, streamed/slow uploads, two-worker saturation, health availability, worker cancellation, trusted proxy handling, shared rolling provider allowance, cooldown and compatibility of echoed expiry metadata. An initial full run exposed five contract failures: returned expiry is now explicitly accepted and discarded before advisor processing; reset security tests now submit only reset fields, preserving their access-control assertions. The Windows sandbox blocked the event loop's local socket pair before request execution; the successful runs allowed local connections while the existing offline fixtures blocked external network access. No live Groq/Shopify requests were made. Widget files were unchanged and browser tests were not rerun. Actual Render proxy identification, quota suitability and traffic performance require production acceptance.

### Frontend stability — R07 (11 October 2026)

The complete local browser run passed **288 checks**, followed by **9 additional edge-case checks** on the final widget implementation. The suite now defines 297 checks when the local DevTools snippet is present. All three widget variants were covered with headless Edge and intercepted external requests; no Groq quota or live Shopify cart was used. Tests cover blocked/full storage, quota compaction, draft validation and navigation, debounced saves, bounded history, focused-card preservation and restored details on short mobile and landscape viewports. The checks exposed an outer minimum height that prevented open cards from fitting on short screens; this was corrected in all three variants. No backend code changed, so the Python suite was not rerun. Actual devices and theme integration remain manual acceptance checks.

Choose tests by the behavior being changed: parser and rule tests for extraction logic, API tests for request or response contracts, session-store tests for persistence, and scenario tests for complete advisor flows. Add live-service checks only when an external call is required; keep deterministic behavior covered with mocks.

## Verified Shopify cart — R04

On 9 October 2026, the offline Python suite passed **368 tests**, with 6 live-service tests deselected. A complete browser run passed **222 checks**; the final focused run passed **42 checks**, including 3 newly added virtual-clock cart timeouts. The browser suite now contains 222 distinct checks when the local DevTools snippet is present. Every external request was intercepted; no store cart was changed and no Groq quota was used.

Cart regressions cover confirmed one-unit additions, locale-aware endpoints, no premature success, errors and lost/invalid responses, timeout without resubmission, changed price/options requiring confirmation, unavailable/missing variants, simultaneous card actions, origin restrictions, mobile layout and restoration without stale cart claims. Python checks cover selected-variant ingestion and legacy purchase links. Live acceptance must still check the actual theme's cart counter/drawer and preservation of existing items. The subsequent Impulse adapter uses the theme's native rebuild event; the widget does not replace its components.

### Impulse drawer synchronization

On 9 October 2026, the public Etualy theme source (Impulse 7.4.1) confirmed that `cart:build` rebuilds cart items, totals, discounts, quantity controls and header counts; `ajaxProduct:added` also opens the drawer and is deliberately not emitted. All **228 browser checks** passed after the adapter change, including 6 new simulated-theme checks covering success/error behavior on all three widgets. The backend was unchanged, so Python tests were not rerun. All browser requests were intercepted; no live cart mutation occurred. The drawer contract is simulated in tests; acceptance on the actual site remains necessary through the updated DevTools snippet.

### Explicit formats and chat purchase preparation

On 9 October 2026, the final offline suite passed **382 Python tests** (6 live-service tests deselected) and **240 browser checks** across the three widgets, followed by 3 additional live-stock-change checks on the final interface. The complete browser suite now contains 243 checks. New regressions cover deterministic purchase parsing, missing/ambiguous product references, preserved requested sizes, format and size-price questions without LLM calls, live option buttons, disabled unavailable formats, price/ID switching, explicit chat confirmation, no default substitution, hostile titles, mobile layout and restoration without automatic purchases. All external service requests were simulated; no live Shopify cart was changed and no Groq quota was consumed.

A simultaneous-add browser check initially depended on a short fixed response delay and failed under load. Its response is now held until the assertions finish, making the concurrency check deterministic. The subsequent complete run passed. Live acceptance should repeat size switching, unavailable options and chat confirmation on Etualy with the updated DevTools snippet.
