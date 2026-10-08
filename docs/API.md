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
| `session_id` | string | Yes | Session key: 1–128 letters, digits, `_` or `-`. Missing, `null`, empty and `default` values are rejected. |
| `session_context` | object or `null` | No | After the first reply, send its `token` and `revision` to detect expired, lost or outdated conversation state. |
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
  "mode": "free",
  "session_context": {
    "token": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "revision": 1,
    "expires_at": 1791547200000
  }
}
```

Product fields depend on the selected card. They can include name, brand, price, product and image URLs, fragrance traits, story, key notes and `card_type`.

### Identified requests and retries

The widget assigns a new `request_id` to each message and preserves it for retries, including after page navigation. The backend serializes chat and reset operations for the same session within the running process; other sessions use independent locks. Requests without `request_id` remain compatible but have no duplicate-result recovery.

For identified requests, session state and the completed response, including session metadata, are committed together in SQLite. Sending the same session, identifier, trimmed message, price constraint and step override again recovers that response without changing state or calling the model again, subject to the session checks below. Reusing an identifier with different input returns `409` (`request_id_conflict`). Rate limits still apply to every HTTP attempt.

The latest 100 complete responses per session are retained. Older identifiers keep their payload fingerprint: retrying one returns `409` (`request_result_expired`) rather than processing it again. Reset clears both session state and request records. Database initialization adds the request table automatically; no catalog ingestion or reindexing is needed.

An exception before the atomic commit leaves no completed result, so the same identifier may be retried. Transient model failures and invalid completions return `503` without a saved response, so the original identifier remains retryable. A normal `200` response, including a guided selection with a fixed introduction, is a completed result: a subsequent customer message gets a new identifier. If the process stops after a model call but before committing, a retry can require another model call.

Session locks are local to one process. Keep the current Render start command with `--workers 1` and one service instance. Multiple workers or replicas require shared coordination before enabling them.

### Session lifetime and continuity

Every new completed message renews a **24-hour inactivity deadline**. Reads, failures and cached retries do not renew it. Responses include `session_context`: a 32-character lowercase hexadecimal `token`, an integer `revision` incremented at each commit, and `expires_at` as Unix epoch milliseconds. Subsequent widget requests send only the token and revision; the server owns expiry.

- Expired sessions, or a supplied token whose session was lost or replaced, return `409` with `session_expired` before model processing.
- A supplied revision that differs from the stored conversation returns `409` with `session_out_of_sync`. A retry may use its original revision to recover the latest completed response; if another message has advanced the session, that older result is rejected.
- Expired state and its request receipts are deleted in small batches at startup and hourly, skipping sessions being processed. Expiry is enforced even before cleanup runs.

Clients supplying only a valid session ID remain supported, but cannot detect lost state or revision mismatches. Session metadata is a continuity mechanism, not user authentication.

The widget performs these checks through the normal chat exchange, without an extra page-load request. On expiry or loss it starts a fresh local conversation, explains the restart and preserves the message in the input for deliberate resubmission. Version-1 saved widget state is retired once on upgrade; any pending message or draft is retained.

The current Render Free deployment has no persistent disk: SQLite can be lost on deploy, restart or spin-down. The 24-hour deadline therefore does not guarantee 24 hours of availability. Durable recovery requires retained storage; see [deployment storage](INDEX_OPERATIONS.md#session-storage-on-render-free).

### Reset request

```json
{
  "session_id": "example-session"
}
```

The response is `{"status":"ok","session_id":"example-session","message":"Sessione azzerata"}`. Reset requires a valid session ID and also rejects `default`. It removes the stored history, active product, guided state and completed request records for the given session. It waits for any operation already holding that session's lock. The widget immediately uses a new session identifier and discards replies from the previous session; aborting the browser request does not cancel model work already running on the backend.

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

The API returns `422` for invalid request data, `409` for a conflicting identifier or an unavailable older result, `429` when a route limit is exceeded, and `503` when the advisor is starting or a downstream service cannot complete the request. An application `429` includes the standard `Retry-After` header. Provider failures can return `503` with codes such as `llm_rate_limit`, `llm_timeout`, `llm_unavailable`, `llm_invalid_response`, `llm_attempts_exhausted` or `chat_deadline_exceeded`; a provider cooldown is forwarded through `Retry-After` when available.

The built-in rate limiter is in-memory and applies separately to chat and reset routes. It is intentionally lightweight for a single service instance: counters are reset after a restart and are not shared between multiple instances.

## Response waits

Chat processing uses a shared 25-second budget, including time waiting for the same-session lock, and at most three provider calls. Intent classification has a 3-second timeout; reply generation has a 10-second timeout, reduced to the remaining budget. These are cooperative bounds, not a hard cancellation of synchronous operations. See [LLM resilience](ADVISOR.md#llm-resilience).

The widget limits its complete HTTP wait, including response-body reading, to 60 seconds. A local timeout offers recovery with the same request identifier and ignores late replies; it cannot cancel work already executing on the server or accelerate a Render cold start. Numeric and HTTP-date `Retry-After` values disable sends and retries until the indicated time, with a countdown retained across navigation and local restart.

## CORS

CORS exposes `Retry-After` so the storefront can read the cooldown header. `ALLOWED_ORIGINS` is a comma-separated list of origins. It defaults to `*`. When the wildcard is configured, the application allows all origins and disables credentialed CORS requests; set explicit origins when credentials are required or access should be restricted.

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
