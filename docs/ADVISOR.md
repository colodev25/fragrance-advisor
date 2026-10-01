# Conversation advisor

`FragranceAdvisor` in `src/advisor.py` coordinates each conversation. It restores the session state, decides whether the request continues a product discussion or needs new recommendations, retrieves catalog candidates when needed, applies application rules, asks the configured Groq model to compose a reply, and saves the updated session.

## Interaction modes

### Guided consultation

The guided flow collects four answers in order:

1. Preferred fragrance family or character
2. Intended recipient
3. Occasion or season
4. Budget

After the last answer, the advisor retrieves and filters candidates using those answers. A successful guided recommendation can return up to three product cards. The current guided options and questions are defined by `GUIDED_STEPS` in `src/advisor.py`.

### Free conversation

Customers can describe what they want directly, ask about a product, or refine a previous request. The advisor uses the conversation history and active product to distinguish a follow-up question from a request to change fragrance. Follow-ups about the active fragrance can return an answer without new product cards; a new search can update the active product.

## Recommendation process

For a request that needs product recommendations, the advisor:

1. Extracts relevant preferences, note requests and price constraints.
2. Retrieves candidates through `FragranceSearchEngine` and the ChromaDB catalog index.
3. Applies deterministic checks and uses product data to enrich the candidate cards.
4. Sends the request and selected catalog context to Groq to produce the conversational explanation.
5. Stores the answer, active product and guided-flow state in `SessionStore`.

The model explains and contextualizes catalog candidates. Product details shown in cards come from the catalog, and the advisor can return no product when the available candidates do not fit the request.

## Session state

Each `session_id` stores:

- Conversation history
- The active fragrance, if one is selected
- Guided-flow step and collected answers
- Last update time in the SQLite record

`SessionStore` reloads persisted state for each request, so the conversation can continue after a server restart when the same session identifier is reused. `POST /reset` clears that session.

## LLM resilience

`src/llm_resilience.py` calls the primary Groq model, retries transient rate-limit, timeout, connection and server errors with exponential delays, then tries the fallback model. If calls still fail, it returns a configured graceful response rather than propagating the LLM error as a generated answer. Model names can be configured with `GROQ_PRIMARY_MODEL` and `GROQ_FALLBACK_MODEL`.

## Responsibilities

| Component | Role |
| --- | --- |
| `src/main.py` | HTTP request handling and application startup |
| `src/advisor.py` | Conversation flow, candidate selection and response orchestration |
| `src/search.py` | ChromaDB retrieval and post-retrieval filtering |
| `src/session_store.py` | SQLite session persistence |
| `src/llm_resilience.py` | Groq retries, model fallback and graceful failure |
