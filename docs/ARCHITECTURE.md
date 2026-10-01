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

`src/main.py` defines the FastAPI application, CORS policy, startup lifecycle, health check, chat routes and reset routes. At startup, if `chroma_db/` is absent or empty, it attempts to create the vector index from `data/catalog.json`, then initializes the advisor. The browser interface in `index.html` manages the chat display and a session identifier in `sessionStorage`; its API base URL is configured in the page source.

### Conversation advisor

`src/advisor.py` coordinates the guided and free-form flows, restores conversation state, identifies active-product follow-ups, applies recommendation rules, enriches product cards and prepares catalog context for the LLM. `src/llm_resilience.py` handles retry and fallback behavior for Groq calls.

### Search and indexing

`src/search.py` queries the persistent ChromaDB collection named `fragrances`, applies price constraints and lexical checks, and returns product metadata and semantic documents. `src/reindex.py` recreates this collection from the current catalog. The default embedding function is ChromaDB's built-in `DefaultEmbeddingFunction`; the reindexer uses cosine distance.

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
