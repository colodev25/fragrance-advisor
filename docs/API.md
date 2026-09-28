# API

## Overview

Fragrance Advisor exposes a lightweight HTTP API through FastAPI.

The API acts as the communication layer between the web interface and the conversational advisor.

```text
Frontend
   │
   ▼
FastAPI
   │
   ▼
FragranceAdvisor
```

---

## Base URL

When running locally:

```text
http://127.0.0.1:8000
```

---

## Endpoints

### `GET /`

Basic application endpoint.

It can be used to verify that the FastAPI application is running.

---

### `POST /chat`

Main endpoint used by the frontend to send a message to the advisor.

#### Request

```json
{
  "message": "Cerco un profumo legnoso ed elegante",
  "session_id": "example-session",
  "max_price": 150,
  "step_override": null
}
```

#### Parameters

| Parameter       | Type   | Required | Description                            |
| --------------- | ------ | -------: | -------------------------------------- |
| `message`       | string |      Yes | User message                           |
| `session_id`    | string |      Yes | Identifier of the conversation session |
| `max_price`     | number |       No | Maximum allowed price                  |
| `step_override` | string |       No | Optional guided-flow step override     |

---

### `POST /chat/`

The trailing-slash version is also exposed for compatibility with clients that submit requests to `/chat/`.

It uses the same request structure as `/chat`.

---

## Session Handling

The `session_id` identifies the conversation.

The frontend generates or maintains the identifier and sends it with subsequent requests.

The backend uses it to retrieve and persist the corresponding session state.

```text
session_id
    │
    ▼
SessionStore
    │
    ▼
SQLite
```

Persistent session information can include:

- conversation history;
- active perfume;
- guided-flow state;
- update timestamp.

This allows conversational context to survive application restarts.

---

## CORS

CORS is configured by the backend to allow requests from the website frontend.

The allowed origins can be configured through the environment:

```env
ALLOWED_ORIGINS=*
```

For production deployments, the value should be restricted to the domains that actually need access to the API.

---

## Error Handling

The API validates incoming requests before passing them to the advisor.

Errors can originate from:

- invalid request data;
- missing required parameters;
- advisor processing;
- external LLM services;
- search or persistence operations.

The API returns an appropriate HTTP error response when request processing cannot be completed.

---

## Request Flow

A typical request follows:

```text
HTTP POST /chat
       │
       ▼
Request Validation
       │
       ▼
FragranceAdvisor.advise()
       │
       ├──► SessionStore
       │
       ├──► Search Engine
       │
       └──► LLM
       │
       ▼
Generated Response
       │
       ▼
HTTP Response
```

---

## Environment Variables

The API and advisor require environment configuration for external services.

Example:

```env
GROQ_API_KEY=your_api_key_here
ALLOWED_ORIGINS=*
```

Secrets must be stored in `.env` and excluded from version control.
