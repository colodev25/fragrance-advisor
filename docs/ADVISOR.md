# Fragrance Advisor

## Overview

The main conversational logic of Fragrance Advisor is implemented in:

```text
src/advisor.py
```

The central component is the `FragranceAdvisor` class.

The advisor acts as the orchestration layer between:

* user messages;
* conversation state;
* guided recommendation flow;
* free conversation;
* semantic search;
* product filtering;
* the language model.

Its main responsibility is to transform a user's request into a set of relevant perfume candidates and an appropriate conversational response.

---

## Main Components

The advisor integrates two main external components:

```text
FragranceAdvisor
│
├── FragranceSearchEngine
│       └── ChromaDB
│
└── LLM client
        └── Groq API
```

The search engine is responsible for retrieving relevant products.

The language model is responsible for interpreting conversational input and generating natural-language responses.

---

## Conversation Modes

The current implementation supports two main interaction modes.

### Guided Mode

Guided mode progressively collects information from the user before performing a recommendation.

The information gathered can include:

* olfactory preferences;
* intended recipient;
* usage occasion;
* budget;
* other relevant constraints.

A simplified flow is:

```text
User
 ↓
Olfactory preferences
 ↓
Recipient
 ↓
Occasion
 ↓
Budget
 ↓
Semantic search
 ↓
Candidate perfumes
 ↓
Recommendation
```

The exact progression is managed by the advisor's conversation state.

---

### Free Mode

Free mode allows the user to interact with the advisor using natural language without following a strictly predefined questionnaire.

The advisor can interpret information contained in the user's message and use it to determine whether a new search is required.

For example, a user may:

* describe the type of perfume they want;
* mention a specific perfume;
* ask for alternatives;
* introduce a budget constraint;
* continue discussing a previously suggested product.

The advisor maintains conversational context through the session.

---

## Session Management

Each conversation is associated with a session identifier.

The session allows the backend to distinguish different conversations and preserve relevant conversational state.

Conceptually:

```text
session_id
    ↓
Conversation state
    ↓
User messages
    ↓
Advisor decisions
    ↓
Recommendations
```

The frontend stores the session identifier in browser `sessionStorage` and sends it with subsequent requests.

A new session can be created when the user restarts the conversation.

---

## User Intent and Constraints

The advisor processes information contained in the user's messages and converts relevant information into search constraints.

One of the most explicit constraints is price.

The advisor can translate a budget expressed through the guided flow into numerical limits that can be passed to the search engine.

Conceptually:

```text
User budget
     ↓
Budget interpretation
     ↓
min_price / max_price
     ↓
Semantic search
```

This allows semantic relevance and price constraints to be handled together.

---

## Candidate Retrieval

The advisor uses the semantic search engine to retrieve candidate products.

The current implementation intentionally retrieves more products than may ultimately be presented to the user.

For example, the advisor can retrieve a larger candidate pool and subsequently perform additional processing.

```text
User request
     ↓
Semantic search
     ↓
Candidate pool
     ↓
Deterministic filtering
     ↓
Relevant products
```

This separation allows the system to avoid relying exclusively on the vector similarity score.

---

## Product Context

When a product is being discussed, the advisor can maintain information about the product within the conversation.

This allows follow-up messages to refer to a previously discussed perfume without necessarily requiring the user to repeat its complete name.

The conversational context can therefore be used for interactions such as:

```text
User:
"Qualcosa di simile a questo ma più economico"

        ↓

Advisor:
Current product + "più economico"
        ↓
Search with price constraint
        ↓
Alternative products
```

---

## Language Model

The advisor uses an OpenAI-compatible client configured to communicate with the Groq API.

The current model configured in the implementation is:

```text
openai/gpt-oss-20b
```

The language model is used for tasks such as:

* interpreting conversational input;
* extracting information from natural language;
* assisting with product-data extraction;
* generating the final assistant response.

The LLM should therefore be considered a component of the orchestration layer rather than the database or search engine itself.

---

## Search and Generation Separation

A key architectural characteristic is the separation between retrieval and generation.

The system does not simply ask the LLM to invent or select perfumes from its own knowledge.

Instead:

```text
User request
     ↓
Advisor
     ↓
Semantic Search
     ↓
Real catalog candidates
     ↓
Advisor
     ↓
LLM
     ↓
Natural-language response
```

This architecture allows the recommendations to be grounded in the available product catalog.

---

## Recommendation Flow

A simplified recommendation cycle is:

```text
1. Receive user message
          ↓
2. Identify conversational context
          ↓
3. Extract relevant constraints
          ↓
4. Determine whether a search is required
          ↓
5. Query semantic search engine
          ↓
6. Retrieve candidate products
          ↓
7. Apply additional constraints
          ↓
8. Provide product context to the LLM
          ↓
9. Generate assistant response
          ↓
10. Return response to frontend
```

Not every user message necessarily triggers a new product search.

Conversational messages can be handled using the existing session context when appropriate.

---

## Current Status

> 🚧 `FragranceAdvisor` is under active development.

The guided flow, free conversation behavior, candidate filtering and prompt strategy may change as the project evolves.

This document describes the current implementation rather than a final product specification.
