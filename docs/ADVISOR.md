# Fragrance Advisor

## Overview

`FragranceAdvisor` is the central orchestration component of the application.

It receives user messages, maintains conversational context, determines the appropriate interaction flow, retrieves relevant fragrances and generates the final response through the configured LLM.

The advisor combines deterministic application logic with semantic search and LLM reasoning.

---

## Responsibilities

The advisor is responsible for:

- managing conversation state;
- handling guided and free-form interactions;
- interpreting user preferences;
- identifying relevant products;
- applying price constraints;
- handling product references and alternatives;
- maintaining the active product context;
- communicating with the LLM;
- persisting session state.

---

## Interaction Modes

### Guided Mode

The guided flow progressively collects relevant information from the customer.

Typical information includes:

- olfactory preferences;
- intended recipient;
- occasion;
- budget.

The advisor uses the collected information to progressively narrow the recommendation space.

---

### Free-form Mode

Users can interact naturally without following a predefined sequence.

Examples include:

```text
"Vorrei qualcosa di fresco per l'estate."

"Mi consigli qualcosa di simile a questo?"

"Hai qualcosa di più economico?"

"Preferisco qualcosa di legnoso ma non troppo intenso."
```

The advisor interprets the request and determines which information or products are relevant.

---

## Conversation State

The advisor maintains contextual information throughout a session.

Relevant state can include:

```text
Session
├── conversation history
├── active perfume
├── guided-flow state
└── timestamps
```

The active perfume allows follow-up requests to refer to a previously discussed product.

For example:

```text
User:
"Parlami di questo profumo."

User:
"Hai qualcosa di simile ma meno costoso?"
```

The second request can be interpreted using the previously established product context.

---

## Session Persistence

Session state is persisted through `SessionStore`.

```text
FragranceAdvisor
       │
       ▼
 SessionStore
       │
       ▼
    SQLite
```

The store supports saving and retrieving session information by `session_id`.

This allows the backend to restore conversational context after the in-memory application state has been lost.

Persistent information includes:

- conversation history;
- active product;
- guided-flow state;
- last update timestamp.

---

## Recommendation Flow

At a high level, recommendation generation follows this process:

```text
User Message
     │
     ▼
Intent / Context Analysis
     │
     ▼
Requirement Extraction
     │
     ▼
Candidate Retrieval
     │
     ▼
Deterministic Filtering
     │
     ▼
Candidate Context
     │
     ▼
LLM Response Generation
     │
     ▼
User Response
```

The LLM is therefore not used as the sole source of product selection.

Product candidates are retrieved from the catalog and processed before being passed to the generation layer.

---

## Semantic Retrieval

When product retrieval is required, the advisor delegates the search operation to the search engine.

The search layer can combine:

- semantic similarity;
- price constraints;
- explicit fragrance-note matching;
- lexical relevance;
- product metadata.

The advisor can request more candidates than are ultimately shown to the user, allowing additional deterministic processing before generating the response.

---

## Product Context

The advisor can maintain an active product throughout a conversation.

This enables contextual requests such as:

- asking for additional information;
- requesting similar products;
- requesting cheaper alternatives;
- changing a previously specified constraint;
- comparing products.

The active product is stored as part of the persistent session state.

---

## Price Constraints

The advisor supports maximum-price requirements.

Price constraints can originate from:

- the guided flow;
- explicit user messages;
- API parameters.

Candidates outside the applicable price constraint can be removed before response generation.

---

## LLM Integration

The advisor communicates with an OpenAI-compatible API endpoint configured for Groq.

The LLM receives:

- the user's current request;
- relevant conversation context;
- retrieved product candidates;
- applicable constraints.

The generated response is then returned through the API.

The model is used primarily for:

- natural-language understanding;
- conversational response generation;
- contextual explanation of recommendations.

Deterministic application logic remains responsible for structured operations such as filtering and session management.

---

## Error and Edge Cases

The advisor must handle cases such as:

- no suitable products found;
- invalid or incomplete user requirements;
- impossible price constraints;
- references to unavailable products;
- changes to previously specified requirements;
- empty or malformed requests.

When the available catalog cannot satisfy a request, the advisor can communicate the limitation instead of fabricating a product recommendation.

---

## Session Lifecycle

A typical session follows this lifecycle:

```text
New session
    │
    ▼
Receive message
    │
    ▼
Load persistent state
    │
    ▼
Process request
    │
    ▼
Generate response
    │
    ▼
Update state
    │
    ▼
Persist session
    │
    ▼
Return response
```

Sessions can subsequently be loaded again using the same `session_id`.

---

## Separation of Responsibilities

The advisor does not directly implement every operation required by the application.

Instead:

| Component          | Responsibility             |
| ------------------ | -------------------------- |
| `main.py`          | HTTP/API layer             |
| `advisor.py`       | Conversation orchestration |
| `search.py`        | Product retrieval          |
| `session_store.py` | Persistent session storage |
| Groq               | LLM inference              |
| ChromaDB           | Vector retrieval           |

This separation keeps conversational logic independent from storage and transport mechanisms.
