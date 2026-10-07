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

`src/main.py` initializes the advisor from the verified active index generation. Indexing is performed before startup, never inside the API lifecycle. Missing, incompatible or incomplete generations leave `/health` at `503`; chat requests receive a structured `503` response. The API validates request bounds and applies an in-memory per-client rate limit. The browser interface in `index.html` manages the chat display and session identifier; its API base URL is configured in the page source.

### Conversation advisor

`src/advisor.py` coordinates the guided and free-form flows, restores conversation state, identifies active-product follow-ups, applies recommendation rules, enriches product cards and prepares catalog context for the LLM. `src/llm_resilience.py` handles retry and fallback behavior for Groq calls.

### Search and indexing

`src/reindex.py` builds a unique `fragrances_<generation>` collection using ChromaDB's local ONNX embedding model (`all-MiniLM-L6-v2`) and cosine distance. It validates the source catalog, checks indexed IDs/count and a search probe, writes a catalog snapshot, then atomically publishes `chroma_db/active.json`. `src/search.py` verifies this manifest and loads its collection; `src/advisor.py` uses that same catalog snapshot. Source catalog updates remain pending until indexing succeeds and the backend restarts. See [index operations](INDEX_OPERATIONS.md).

### Catalog ingestion

`src/ingest.py` reads a Shopify store's public `/products.json` endpoint, cleans and transforms product fields, extracts fragrance data from product sections and tags, and writes the catalog plus availability and rejected-product datasets. When configured, Groq can help extract fragrance pyramid data if other extraction methods do not find it.

### Session persistence

`src/session_store.py` stores conversation history, active fragrance, guided-flow state and update timestamp in SQLite. The default database is `data/sessions.db`; `SESSIONS_DB_PATH` can override it. SQLite WAL mode is enabled for session storage.

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

The GitHub Actions catalog workflow runs ingestion on a schedule or manual dispatch and pushes changes to `feature/new-site`. It does not rebuild ChromaDB. The CI test workflow separately builds an index from the checked-out catalog before running its selected tests.

## Repository map

| Path                    | Responsibility                                   |
| ----------------------- | ------------------------------------------------ |
| `src/main.py`           | FastAPI application and routes                   |
| `src/advisor.py`        | Conversation and recommendation orchestration    |
| `src/search.py`         | Runtime semantic retrieval and filtering         |
| `src/reindex.py`        | ChromaDB index generation                        |
| `src/ingest.py`         | Shopify product ingestion and normalization      |
| `src/session_store.py`  | SQLite session persistence                       |
| `src/llm_resilience.py` | LLM retry and model fallback                     |
| `data/`                 | Product JSON datasets and local session database |
| `index.html`            | Browser chat interface                           |
| `tests/`                | API, parser, session, resilience and E2E tests   |
| `.github/workflows/`    | CI tests and scheduled catalog synchronization   |
