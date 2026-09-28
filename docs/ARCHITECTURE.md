# Architecture

## Overview

Fragrance Advisor is organized as a modular application in which product ingestion, semantic search, conversational logic, persistence and HTTP communication are handled by separate components.

The main runtime flow is:

```text
                    ┌──────────────┐
                    │   Frontend   │
                    │  index.html  │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   FastAPI    │
                    │   main.py    │
                    └──────┬───────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │ FragranceAdvisor   │
                 │    advisor.py      │
                 └───┬──────┬─────┬──┘
                     │      │     │
             ┌───────┘      │     └──────────┐
             ▼              ▼                ▼
       ┌───────────┐  ┌───────────┐   ┌────────────┐
       │  Search   │  │    LLM    │   │  Session   │
       │  Engine   │  │   Groq    │   │   Store    │
       └─────┬─────┘  └───────────┘   └─────┬──────┘
             │                              │
             ▼                              ▼
        ┌───────────┐                 ┌──────────┐
        │ ChromaDB  │                 │  SQLite  │
        └───────────┘                 └──────────┘
```

---

## Project Components

### `src/main.py`

Provides the FastAPI application and exposes the HTTP interface used by the frontend.

Responsibilities include:

- application initialization;
- CORS configuration;
- request validation;
- `/chat` endpoint handling;
- communication with `FragranceAdvisor`.

---

### `src/advisor.py`

Contains the central `FragranceAdvisor` class.

It coordinates:

- conversation state;
- guided and free-form interaction;
- user preferences;
- product context;
- semantic retrieval;
- deterministic filtering;
- recommendation generation;
- LLM interaction;
- session persistence.

The advisor acts as the orchestration layer between the API, search engine, LLM and session store.

---

### `src/search.py`

Implements the semantic fragrance retrieval layer.

It:

1. loads the product catalog;
2. creates or accesses the ChromaDB collection;
3. generates embeddings;
4. performs semantic retrieval;
5. applies deterministic filters;
6. performs additional result processing.

The search engine is used by the advisor when product candidates are required.

---

### `src/session_store.py`

Provides persistent storage for conversational sessions using SQLite.

The session store is responsible for saving and retrieving information such as:

- conversation history;
- currently active perfume;
- guided-flow state;
- session timestamps.

The backend can therefore reconstruct a session after the in-memory advisor state is lost or the application is restarted.

---

### `src/ingest.py`

Implements the product data ingestion pipeline.

It retrieves product information and transforms it into the structured datasets consumed by the rest of the application.

The main output is:

```text
data/catalog.json
```

Additional files contain out-of-stock and rejected products.

---

### `src/reindex.py`

Rebuilds the persistent ChromaDB index from the current catalog.

Its role is intentionally separate from ingestion:

```text
ingest.py
    ↓
catalog.json
    ↓
reindex.py
    ↓
ChromaDB index
```

This allows the catalog and the semantic index to be updated independently.

---

### `index.html`

Provides the browser-based chat interface.

The frontend:

- displays the conversation;
- manages the client-side session identifier;
- sends messages to the FastAPI backend;
- displays recommendations and product information;
- manages chat interaction controls.

---

## Data Flow

### Catalog flow

```text
Product Source
      │
      ▼
  ingest.py
      │
      ▼
catalog.json
      │
      ▼
  reindex.py
      │
      ▼
 ChromaDB
```

### Conversation flow

```text
User
 │
 ▼
Frontend
 │
 ▼
FastAPI
 │
 ▼
FragranceAdvisor
 │
 ├──► SessionStore ──► SQLite
 │
 ├──► SearchEngine ──► ChromaDB
 │
 └──► LLM ───────────► Groq
 │
 ▼
Response
 │
 ▼
Frontend
```

---

## Session Persistence

Sessions use a two-level model.

The frontend stores and sends a `session_id`, while the backend uses that identifier to access persistent session data through `SessionStore`.

```text
Browser
   │
   │ session_id
   ▼
FastAPI
   │
   ▼
FragranceAdvisor
   │
   ▼
SessionStore
   │
   ▼
SQLite
```

The SQLite database stores the state required to reconstruct an ongoing conversation.

---

## External Services

The application can communicate with external services for:

- product data ingestion;
- LLM inference;
- embedding generation.

API credentials are supplied through environment variables and are not part of the source code.

---

## Design Principles

The architecture separates responsibilities between:

- **data acquisition**;
- **data transformation**;
- **semantic retrieval**;
- **conversation orchestration**;
- **LLM generation**;
- **session persistence**;
- **HTTP communication**.

This separation allows individual components to evolve without requiring the entire application to be rewritten.
