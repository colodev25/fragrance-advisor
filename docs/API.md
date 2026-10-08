# HTTP API

The FastAPI application in `src/main.py` exposes the chat service to the browser interface and other clients. For local development, run `uvicorn src.main:app --reload`; the base URL is `http://127.0.0.1:8000`.

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /` | Lightweight service status. Returns `ok` or `degraded`. |
| `GET /health` | Readiness check. Returns `200` only when the advisor and search index are ready; otherwise returns `503`. |
| `POST /chat` or `POST /chat/` | Send a message and receive the advisor response. |
| `POST /reset` or `POST /reset/` | Clear a conversation session. |

### Chat request

```json
{
  "message": "Cerco un profumo legnoso ed elegante",
  "session_id": "example-session",
  "request_id": "req_example-001",
  "max_price": 150,
  "step_override": null
}
```

| Field | Type | Required | Behavior |
| --- | --- | --- | --- |
| `message` | string | Yes | Trimmed user message, from 1 to 2,000 characters. |
| `session_id` | string or `null` | No | Session key; defaults to `default`. It accepts letters, digits, `_` and `-`, up to 128 characters. |
| `request_id` | string or `null` | No | Unique identifier for one logical message, from 1 to 128 letters, digits, `_` or `-`. Reuse it with the same payload when retrying that message. |
| `max_price` | number or `null` | No | Maximum price constraint from 0 to 10,000. |
| `step_override` | integer or `null` | No | Optional guided-flow step from 1 to 4. |

The response is the advisor's JSON object. It includes `reply`, `products`, `options`, `step`, and `mode` where applicable. `products` contains structured product cards; `options` contains guided-flow choices. `step` is the active guided step or `null`, and `mode` identifies guided or free conversation responses.

Example response shape:

```json
{
  "reply": "Ecco una fragranza in linea con la tua richiesta.",
  "options": [],
  "products": [],
  "step": null,
  "mode": "free"
}
```

Product fields depend on the selected card. They can include name, brand, price, product and image URLs, fragrance traits, story, key notes and `card_type`.

### Identified requests and retries

The widget assigns a new `request_id` to each message and preserves it for retries, including after page navigation. The backend serializes chat and reset operations for the same session within the running process; other sessions use independent locks. Requests without `request_id` remain compatible but have no duplicate-result recovery.

For identified requests, session state and the completed response are committed together in SQLite. Sending the same session, identifier, trimmed message, price constraint and step override again returns that response without changing conversation state or calling the model again. Reusing an identifier with different input returns `409` (`request_id_conflict`). Rate limits still apply to every HTTP attempt.

The latest 100 complete responses per session are retained. Older identifiers keep their payload fingerprint: retrying one returns `409` (`request_result_expired`) rather than processing it again. Reset clears both session state and request records. Database initialization adds the request table automatically; no catalog ingestion or reindexing is needed.

An exception before the atomic commit leaves no completed result, so the same identifier may be retried. A normal `200` response, including an advisor fallback message, is a completed result: a subsequent customer message gets a new identifier. If the process stops after a model call but before committing, a retry can require another model call.

Session locks are local to one process. Keep the current Render start command with `--workers 1` and one service instance. Multiple workers or replicas require shared coordination before enabling them. Recovery after a restart depends on retaining the SQLite database; Render storage durability remains a separate deployment concern.

### Reset request

```json
{
  "session_id": "example-session"
}
```

The response is `{"status":"ok","session_id":"example-session","message":"Sessione azzerata"}`. Reset removes the stored history, active product, guided state and completed request records for the given session. It waits for any operation already holding that session's lock. The widget immediately uses a new session identifier and discards replies from the previous session; aborting the browser request does not cancel model work already running on the backend.

## Validation, limits and errors

Requests use one error format:

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Hai inviato troppe richieste. Riprova tra qualche istante."
  }
}
```

The API returns `422` for invalid request data, `409` for a conflicting identifier or an unavailable older result, `429` when a route limit is exceeded, and `503` when the advisor is starting or a downstream service cannot complete the request. A `429` response includes the standard `Retry-After` header.

The built-in rate limiter is in-memory and applies separately to chat and reset routes. It is intentionally lightweight for a single service instance: counters are reset after a restart and are not shared between multiple instances.

## CORS

`ALLOWED_ORIGINS` is a comma-separated list of origins. It defaults to `*`. When the wildcard is configured, the application allows all origins and disables credentialed CORS requests; set explicit origins when credentials are required or access should be restricted.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `GROQ_API_KEY` | Required credential for Groq-backed advisor initialization. | None |
| `GROQ_PRIMARY_MODEL` | Primary model name. | `openai/gpt-oss-120b` |
| `GROQ_FALLBACK_MODEL` | Fallback model name. | `openai/gpt-oss-20b` |
| `ALLOWED_ORIGINS` | Comma-separated browser origins allowed by CORS. | `*` |
| `SESSIONS_DB_PATH` | Optional SQLite database path. | `data/sessions.db` |
| `RATE_LIMIT_ENABLED` | Enable the application rate limiter. | `true` |
| `CHAT_RATE_LIMIT_PER_MINUTE` | Maximum `/chat` requests per client each minute. | `30` |
| `RESET_RATE_LIMIT_PER_MINUTE` | Maximum `/reset` requests per client each minute. | `10` |
| `RATE_LIMIT_TRUST_PROXY_HEADERS` | Use `X-Forwarded-For` to identify clients behind a trusted reverse proxy. | `false` |

Keep credentials out of source control. The advisor and ingestion modules load a root `.env` file, which is suitable for local `GROQ_API_KEY`, `SESSIONS_DB_PATH` and `SHOPIFY_STORE_URL` configuration. `ALLOWED_ORIGINS` is read by `src/main.py` when the app module is imported, before the advisor loads `.env`; set it in the process environment before starting the server (or configure Uvicorn to load the file). The model names are read when `src/llm_resilience.py` is imported, so configure `GROQ_PRIMARY_MODEL` and `GROQ_FALLBACK_MODEL` in the process environment before startup as well.

Set `RATE_LIMIT_TRUST_PROXY_HEADERS=true` only when the application is behind a trusted proxy that overwrites `X-Forwarded-For`, such as the configured production proxy. Otherwise a direct caller could provide a forged header and bypass an IP-based limit.
