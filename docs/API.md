# HTTP API

The FastAPI application in `src/main.py` exposes the chat service to the browser interface and other clients. For local development, run `uvicorn src.main:app --reload`; the base URL is `http://127.0.0.1:8000`.

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /` | Health check; returns `{"status":"ok","service":"Etualy Olfactive Advisor API"}`. |
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
| `message` | string | Yes | User message sent to the advisor. |
| `session_id` | string or `null` | No | Session key; defaults to `default`. |
| `max_price` | number or `null` | No | Maximum price constraint in the search flow. |
| `step_override` | integer or `null` | No | Optional guided-flow step supplied to the advisor. |

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

## Validation and errors

Request bodies are validated by Pydantic. Missing required fields or invalid field types produce FastAPI's standard `422` validation response. The `/chat` handler returns a temporary startup message with an empty product list if the advisor has not initialized yet. Runtime exceptions from downstream search or persistence operations are not converted into a documented custom error schema.

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

Keep credentials out of source control. The advisor and ingestion modules load a root `.env` file, which is suitable for local `GROQ_API_KEY`, `SESSIONS_DB_PATH` and `SHOPIFY_STORE_URL` configuration. `ALLOWED_ORIGINS` is read by `src/main.py` when the app module is imported, before the advisor loads `.env`; set it in the process environment before starting the server (or configure Uvicorn to load the file). The model names are read when `src/llm_resilience.py` is imported, so configure `GROQ_PRIMARY_MODEL` and `GROQ_FALLBACK_MODEL` in the process environment before startup as well.
