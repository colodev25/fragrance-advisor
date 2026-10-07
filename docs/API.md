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
  "max_price": 150,
  "step_override": null
}
```

| Field | Type | Required | Behavior |
| --- | --- | --- | --- |
| `message` | string | Yes | Trimmed user message, from 1 to 2,000 characters. |
| `session_id` | string or `null` | No | Session key; defaults to `default`. It accepts letters, digits, `_` and `-`, up to 128 characters. |
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

### Reset request

```json
{
  "session_id": "example-session"
}
```

The response is `{"status":"ok","session_id":"example-session","message":"Sessione azzerata"}`. Reset removes the stored history, active product and guided state for the given session.

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

The API returns `422` for invalid request data, `429` when a route limit is exceeded, and `503` when the advisor is starting or a downstream service cannot complete the request. A `429` response includes the standard `Retry-After` header.

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
