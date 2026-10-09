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

### Storefront purchases

Cart operations run directly between the widget and Shopify, independently of chat/Render/Groq. On the same Etualy origin, the widget checks the exact variant through the localized Product Ajax API, then adds one unit through Cart Ajax. Changed price/options require explicit confirmation; ambiguous outcomes are not automatically retried. `src/cart_product.py` supplies verified catalog variant fields and legacy permalink compatibility. For Etualy's Impulse theme, a confirmed addition dispatches `cart:build`: the native cart form refreshes drawer contents, totals, quantity controls and counters while keeping the drawer closed. Different themes require a separate adapter. See [purchase integration](UI_UX.md#purchase-integration).

### Conversation advisor

`src/advisor.py` coordinates the guided and free-form flows, restores conversation state, identifies active-product follow-ups, applies recommendation rules, enriches product cards and prepares catalog context for the LLM. `src/llm_resilience.py` handles retry and fallback behavior for Groq calls. `src/chat_budget.py` scopes the chat deadline and provider-call allowance to each request; catalog enrichment retains its separate batch policy. Transient chat failures are retryable HTTP errors, rather than saved conversation replies.

`src/product_identity.py` prepares deterministic name aliases and matching patterns for the loaded snapshot. It distinguishes brand, concentration and declared title size, prioritizes more specific names and returns an explicit ambiguity instead of the first catalog record. Pending clarification stores candidate IDs and the original request in session state; existing widget quick replies confirm the choice without an additional API endpoint or model call.

`src/recommendation_preferences.py` centralizes evidence and admission for both modes. Required constraints are checked against the complete runtime catalog; semantic retrieval ranks the surviving products. Confirmed preference matches take priority, with explicit notices for partial alternatives. The profile persists with session state, and stock, budget or note exclusions cannot be bypassed by the model's candidate selection.

### Search and indexing

`src/reindex.py` builds a unique `fragrances_<generation>` collection using ChromaDB's local ONNX embedding model (`all-MiniLM-L6-v2`) and cosine distance. It validates the source catalog, checks indexed IDs/count and a search probe, writes a catalog snapshot, then atomically publishes `chroma_db/active.json`. `src/search.py` verifies this manifest and loads its collection; `src/advisor.py` uses that same catalog snapshot. Source catalog updates remain pending until indexing succeeds and the backend restarts. See [index operations](INDEX_OPERATIONS.md).

### Catalog ingestion

`src/ingest.py` reads Shopify's public `/products.json`, normalizes commercial data and extracts fragrance fields deterministically, without LLM requests. Valid cached enrichment is preserved across price and availability changes. `src/catalog_jobs.py` maintains a persistent queue and processes incomplete available products separately, with token reservations, request pacing and deferred retries. `src/catalog_enrichment.py` validates source evidence and distinguishes explicit fragrance information from inferred classifications. See [catalog pipeline](DATA_PIPELINE.md).

### Session persistence

`src/session_store.py` stores conversation history, active fragrance, guided-flow state, update timestamp, version/expiry metadata and a private credential hash in SQLite. The default database is `data/sessions.db`; `SESSIONS_DB_PATH` can override it. WAL mode is enabled and each connection is explicitly closed after use.

Sessions expire after 24 hours without a new completed message. An off-thread maintenance task runs at startup and hourly, deleting expired state and receipts in bounded batches under per-session locks. Request processing also checks expiry, clears temporary RAM copies on completion and refreshes the active product by catalog ID. The widget creates a cryptographic credential before its first message and sends it in normal chat/reset JSON bodies. The server atomically claims a new identifier, stores only the credential hash and checks ownership before continuing, replaying or clearing a session. The widget also sends its token/revision in normal chat requests to detect missing or stale state and restart coherently while preserving the customer's draft. No extra page-load HTTP check is introduced.

Render Free has no persistent disk: these sessions can disappear before their inactivity deadline on deploy, restart or spin-down. The current design handles that loss explicitly; it does not provide durable storage across those events. See [session storage](INDEX_OPERATIONS.md#session-storage-on-render-free).

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
| `src/product_identity.py` | Deterministic named-product matching and clarification candidates |
| `src/recommendation_preferences.py` | Catalog evidence, persistent preferences and deterministic admission |
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

### Shared live variant flow

`src/purchase_intent.py` prepares explicit purchase and format requests without provider calls. Catalog identity and pending clarifications remain in the advisor's authenticated session. The browser uses the same live-variant selection and confirmation flow for recommendation cards and chat purchase cards: initial read, explicit option selection, fresh preflight, then one confirmed Ajax addition. Variant IDs/options/prices come from Shopify product JSON; history retains the chosen ID and display data but reloads availability. The existing Impulse adapter refreshes the drawer only after a verified addition.
