# Architecture

Fragrance Advisor separates catalog ingestion, product retrieval, conversation handling, session persistence and HTTP transport. The browser interface sends chat requests to the FastAPI service; the advisor combines catalog candidates with Groq-generated explanations.

## Runtime components

```text
Browser interface (index.html)
              │ HTTP
              ▼
      FastAPI (src/main.py)
              │
              ▼
 FragranceAdvisor (src/advisor.py)
       ┌──────┼─────────┐
       ▼      ▼         ▼
    Search   Groq   SessionStore
       │                │
       ▼                ▼
   ChromaDB           SQLite
```

### API and interface

`src/main.py` initializes the advisor from the verified active index generation. Indexing is performed before startup, never inside the API lifecycle. Missing, incompatible or incomplete generations leave `/health` at `503`; chat requests receive a structured `503` response. The API validates request bounds and applies an in-memory per-client rate limit. The browser interface in `index.html` and its Shopify snippet render received fields through DOM properties and validate HTTP(S) URLs. Conversation state is stored as versioned JSON and recreated safely; its API base URL is configured in the page source. See [widget UI/UX](UI_UX.md).

### Conversation advisor

`src/advisor.py` coordinates the guided and free-form flows, restores conversation state, identifies active-product follow-ups, applies recommendation rules, enriches product cards and prepares catalog context for the LLM. `src/llm_resilience.py` handles retry and fallback behavior for Groq calls. `src/chat_budget.py` scopes the chat deadline and provider-call allowance to each request; catalog enrichment retains its separate batch policy. Transient chat failures are retryable HTTP errors, rather than saved conversation replies.

### Search and indexing

`src/reindex.py` builds a unique `fragrances_<generation>` collection using ChromaDB's local ONNX embedding model (`all-MiniLM-L6-v2`) and cosine distance. It validates the source catalog, checks indexed IDs/count and a search probe, writes a catalog snapshot, then atomically publishes `chroma_db/active.json`. `src/search.py` verifies this manifest and loads its collection; `src/advisor.py` uses that same catalog snapshot. Source catalog updates remain pending until indexing succeeds and the backend restarts. See [index operations](INDEX_OPERATIONS.md).

### Catalog ingestion

`src/ingest.py` reads Shopify's public `/products.json`, normalizes commercial data and extracts fragrance fields deterministically, without LLM requests. Valid cached enrichment is preserved across price and availability changes. `src/catalog_jobs.py` maintains a persistent queue and processes incomplete available products separately, with token reservations, request pacing and deferred retries. `src/catalog_enrichment.py` validates source evidence and distinguishes explicit fragrance information from inferred classifications. See [catalog pipeline](DATA_PIPELINE.md).

### Session persistence

`src/session_store.py` stores conversation history, active fragrance, guided-flow state and update timestamp in SQLite. The default database is `data/sessions.db`; `SESSIONS_DB_PATH` can override it. SQLite WAL mode is enabled for session storage.

`src/conversation_requests.py` serializes chat and reset for each session within the single API process. SQLite also stores completed identified requests: state and response share one transaction, allowing a lost response to be recovered without repeating model work. The latest 100 responses per session are retained; older identifiers remain recognized. The widget allows one active request, preserves its identity across navigation and ignores previous-session replies after reset. See [API request coordination](API.md#identified-requests-and-retries).

## Catalog and request flows

```text
Shopify /products → src/ingest.py → data/catalog.json
                                            │
                                            ▼
                                      src/reindex.py
                                            │
                                            ▼
                                          ChromaDB
```

```text
Browser → FastAPI → FragranceAdvisor → Search → ChromaDB
                           │
                           ├── Groq for conversational interpretation and replies
                           └── SessionStore → SQLite
```

Separate GitHub Actions workflows synchronize Shopify and progressively enrich the catalog. They share a concurrency group, publish catalog/queue changes to `feature/new-site` and do not rebuild ChromaDB. Render builds the index during deployment. The CI workflow independently builds an index before its selected tests.

## Repository map

| Path                    | Responsibility                                   |
| ----------------------- | ------------------------------------------------ |
| `src/main.py`           | FastAPI application and routes                   |
| `src/advisor.py`        | Conversation and recommendation orchestration    |
| `src/search.py`         | Runtime semantic retrieval and filtering         |
| `src/reindex.py`        | ChromaDB index generation                        |
| `src/ingest.py`         | Shopify product ingestion and normalization      |
| `src/catalog_jobs.py`   | Persistent enrichment queue and nightly budgets  |
| `src/catalog_enrichment.py` | Source evidence validation and extraction cache |
| `src/session_store.py`  | SQLite session persistence                       |
| `src/conversation_requests.py` | Per-session coordination and request conflicts |
| `src/llm_resilience.py` | LLM retry and model fallback                     |
| `src/chat_budget.py` | Chat processing deadline and provider-call allowance |
| `data/`                 | Product JSON datasets and local session database |
| `index.html`            | Browser chat interface                           |
| `tests/`                | API, parser, session, resilience and E2E tests   |
| `.github/workflows/`    | CI tests and scheduled catalog synchronization   |
