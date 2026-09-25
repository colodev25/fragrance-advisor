# Architecture

## Overview

Fragrance Advisor is a conversational AI system designed to assist users in selecting perfumes from an e-commerce catalog.

The current architecture is composed of five main layers:

```text
                    ┌──────────────────────┐
                    │      Shopify         │
                    │   Product Catalog    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │      ingest.py       │
                    │  Data ingestion and  │
                    │     enrichment       │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    catalog.json      │
                    │   Structured data    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │      search.py       │
                    │ Semantic search +    │
                    │      ChromaDB        │
                    └──────────┬───────────┘
                               │
                               ▼
┌────────────────┐    ┌──────────────────────┐
│   index.html   │───►│       main.py        │
│    Frontend    │HTTP│       FastAPI        │
└────────────────┘    └──────────┬───────────┘
                                 │
                                 ▼
                      ┌──────────────────────┐
                      │      advisor.py      │
                      │ Conversational logic │
                      └──────────┬───────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
             ┌──────────────┐          ┌──────────────┐
             │   ChromaDB   │          │    Groq LLM  │
             │ Search engine│          │   AI model   │
             └──────────────┘          └──────────────┘
```

## Components

### `index.html`

The frontend provides the conversational interface used by the customer.

It contains the HTML, CSS and JavaScript required to:

* display the chat interface;
* send messages to the backend;
* display assistant responses;
* manage the conversational session;
* provide quick interaction options;
* handle the restart of a conversation;
* display product-related links.

The frontend communicates with the backend through the `/chat` API endpoint.

The current development version is designed around the new website integration and is therefore located directly in the repository root.

---

### `src/main.py`

`main.py` provides the HTTP API through FastAPI.

Its main responsibility is to act as the bridge between the frontend and the `FragranceAdvisor` class.

The general request flow is:

```text
Frontend
   │
   │ POST /chat
   ▼
FastAPI
   │
   ▼
ChatRequest
   │
   ▼
FragranceAdvisor
   │
   ▼
Response
```

The API receives the user message together with session and optional filtering information, then delegates the actual conversational logic to `advisor.py`.

---

### `src/advisor.py`

`advisor.py` contains the main conversational logic of the application.

The central class is:

```python
FragranceAdvisor
```

It coordinates:

* conversation state;
* guided and free conversation modes;
* interpretation of user requests;
* semantic search;
* price constraints;
* candidate selection;
* interaction with the language model;
* generation of the final response.

This module represents the main orchestration layer of the application.

---

### `src/search.py`

`search.py` implements the semantic search engine.

The catalog is transformed into searchable embeddings and stored in ChromaDB.

The search layer is responsible for finding products that are semantically relevant to a user's request.

The current embedding model is:

```text
paraphrase-multilingual-MiniLM-L12-v2
```

and cosine distance is used for similarity.

---

### `src/ingest.py`

`ingest.py` implements the product data ingestion pipeline.

Its main responsibilities are:

1. retrieve products from the Shopify catalog;
2. clean product descriptions;
3. extract product information;
4. identify olfactory notes;
5. enrich products with structured information;
6. generate semantic representations;
7. produce the local JSON catalog.

This module is primarily used to prepare or update the dataset rather than during normal chat interactions.

---

## Data Flow

The complete application can be viewed as two connected pipelines.

### Catalog pipeline

```text
Shopify
   ↓
ingest.py
   ↓
Product cleaning
   ↓
Data extraction
   ↓
Olfactory information
   ↓
Semantic enrichment
   ↓
catalog.json
   ↓
search.py
   ↓
ChromaDB
```

### User interaction pipeline

```text
User
   ↓
index.html
   ↓
POST /chat
   ↓
main.py
   ↓
FragranceAdvisor
   ↓
Semantic Search
   ↓
Candidate perfumes
   ↓
LLM
   ↓
Assistant response
   ↓
index.html
```

## External Services

The current architecture interacts with external services for:

* product catalog retrieval from Shopify;
* language-model inference through the Groq API.

Sensitive credentials such as API keys must be provided through environment variables and must not be committed to the repository.

## Current Status

> 🚧 The project is currently under active development on `feature/new-site`.

The architecture described here represents the current implementation and may change as the new website integration is completed.
