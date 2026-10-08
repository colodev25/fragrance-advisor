# Testing

The project uses pytest. Tests cover the HTTP API, catalog parsing and advisor rules, session persistence, LLM retry behavior, and end-to-end recommendation scenarios.

## Test files

| File | Coverage |
| --- | --- |
| tests/test_api.py | Health check, chat and reset routes, response shape, request validation and CORS preflight. |
| tests/test_parsers.py | Note cleaning, note extraction, gender and season detection, price constraints, intent routing and guided-flow steps. |
| tests/test_session_store.py | SQLite defaults, save and load, updates, clearing, concurrent writes, restart persistence and reset through the API. |
| tests/test_conversation_requests.py | Per-session serialization, independent customers, concurrent duplicates, reset during processing, atomic state/result commits, restart recovery, identifier conflicts, response pruning, schema migration and HTTP retry contracts. Uses temporary SQLite databases and mocked processing without constructing external clients. |
| tests/test_llm_resilience.py | Retry delays, fallback model, concurrent calls, private reasoning protection, truncated answers, candidate selection validation, graceful failure and an optional live Groq check. |
| tests/test_rate_limit.py | Per-client and per-route request limits. |
| tests/test_catalog_integrity.py | Catalog validation, atomic writes, generation activation, failed builds, removed products and interrupted ingestion, without external services. |
| tests/test_catalog_enrichment.py | Source evidence, partial merges, unpositioned notes, explicit versus inferred families, cache reuse/invalidation, quota cooldowns, failure suspension and removal of generic notes, without external calls. |
| tests/test_catalog_jobs.py | Synchronization without Groq, stock transitions, queue lifecycle, empty results, deferred retries and persistent token reservations, using temporary datasets and mocked clients. |
| tests/test_widget_security.cjs | Real-browser checks for both widgets: safe rendering, navigation, restored actions, concurrent sends, duplicate retries, message identity, pending-request recovery, retired retries and late responses after reset. All network requests are intercepted. |
| tests/test_scenarios_e2e.py | Full advisor scenarios for note and season requests, product follow-ups, cheaper alternatives, unsupported requests and guided recommendations. |

## Run tests

Install the project dependencies and pytest, then run:

    pytest

Run a single test module with:

    pytest tests/test_api.py
    pytest tests/test_session_store.py

pytest.ini registers the e2e marker. Tests in test_scenarios_e2e.py are skipped unless a Groq API key, data/catalog.json and chroma_db/ are available. The live model check in test_llm_resilience.py is also skipped when GROQ_API_KEY is unset. That live check makes external API calls.

The API tests run the application lifespan, which initializes the real advisor; the parser tests also initialize the advisor. Both therefore need a valid GROQ_API_KEY even though test requests or LLM calls are mocked after initialization. A local .env can provide the key through the advisor's load_dotenv() call, or set it in the shell.

## Continuous integration

.github/workflows/tests.yml uses Python 3.11, installs project dependencies and pytest, builds a local ChromaDB index, then runs:

    pytest tests/test_api.py tests/test_parsers.py tests/test_session_store.py tests/test_conversation_requests.py tests/test_catalog_integrity.py tests/test_catalog_enrichment.py tests/test_catalog_jobs.py tests/test_llm_resilience.py -m "not e2e" -v

The workflow passes GROQ_API_KEY from a repository secret and sets SESSIONS_DB_PATH=:memory:. It includes mocked LLM resilience tests, excludes the live e2e model check and does not run test_scenarios_e2e.py.

## Widget browser checks

The separate JavaScript suite uses Node.js and Playwright with a Chromium-based browser. It runs the actual scripts from `index.html` and `snippets/etualy-advisor.liquid`. Test-only hooks are injected in memory; the production files do not expose them. The HTML fixture is served as UTF-8, as required by the storefront document.

```sh
node --test --test-reporter=spec tests/test_widget_security.cjs
```

Playwright must be resolvable by Node. If using an existing runtime rather than a project installation, set `WIDGET_PLAYWRIGHT_MODULE` to its Playwright package directory. Set `WIDGET_BROWSER_EXECUTABLE` to an installed Chromium, Chrome or Edge executable; otherwise Playwright uses its installed Chromium. These variables are for tests only. The local verification used Playwright 1.62.1 and headless Edge.

All page requests are intercepted: HTML, API responses and a sample image are supplied locally; other requests are blocked. No Groq key, Shopify access or running backend is required. Browser contexts and temporary profiles close after the run. This suite contains 46 checks and is currently separate from the Python CI command above; browser CI integration remains part of the test-maintenance work.

Request-coordination checks deliberately deliver both successful and failed responses after cancellation, while a new session is waiting. They also simulate navigation before a response arrives and verify recovery with the original request identifier and a single customer message.

## Adding coverage

Choose tests by the behavior being changed: parser and rule tests for extraction logic, API tests for request or response contracts, session-store tests for persistence, and scenario tests for complete advisor flows. Add live-service checks only when an external call is required; keep deterministic behavior covered with mocks.
