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

Free-search and alternative recommendations require a JSON object with `selection` (a supplied candidate ID, or `null`) and a non-empty `reply`. Invalid JSON, unknown IDs and missing fields trigger the fallback model. If neither model returns a valid selection, the customer receives a retry message without product cards; the previous active fragrance is preserved. An explicit `null` selection clears the active fragrance. No product is inferred from its name or selected automatically from the first search result.

## Session state

Each `session_id` stores:

- Conversation history
- The active fragrance, if one is selected
- Guided-flow step and collected answers
- Last update time in the SQLite record

`SessionStore` reloads persisted state for each request, so the conversation can continue after a server restart when the same session identifier is reused. `POST /reset` clears that session.

`src/conversation_requests.py` coordinates the complete load/process/save operation and reset with a lock per session. Waiting requests keep a reference to that lock; unused locks are removed. This coordination assumes the current deployment with one worker and one service instance.

An optional `request_id` identifies one message. Before processing, the advisor checks its saved result and payload fingerprint. A matching completed request returns the saved response; conflicting input is rejected. New results are saved atomically with session state. Transient failures before commit can be retried, while a completed fallback reply also counts as a saved result. SQLite retains 100 complete responses per session and fingerprints for older identifiers, until reset or session cleanup. See [API retry semantics](API.md#identified-requests-and-retries).

The advisor retains at most 40 recent history messages (20 complete exchanges) when loading and saving a conversation. Active fragrance and guided preferences are stored separately. This limit concerns backend conversation state; widget history is managed by the frontend.

## LLM resilience

`src/llm_resilience.py` calls the primary Groq model, retries transient rate-limit, timeout, connection and server errors with exponential delays, then tries the fallback model. If calls still fail, it returns a configured graceful response rather than propagating the LLM error as a generated answer. Model names can be configured with `GROQ_PRIMARY_MODEL` and `GROQ_FALLBACK_MODEL`.

Empty or truncated answers are rejected. When an empty answer exhausts a supplied token budget, one attempt uses a larger budget before falling back. Internal reasoning fields are never returned to customers. Candidate-selection validation also applies to this recovery attempt. Logs omit response text and provider error bodies.

## Responsibilities

| Component | Role |
| --- | --- |
| `src/main.py` | HTTP request handling and application startup |
| `src/advisor.py` | Conversation flow, candidate selection and response orchestration |
| `src/search.py` | ChromaDB retrieval and post-retrieval filtering |
| `src/session_store.py` | SQLite session persistence |
| `src/llm_resilience.py` | Groq retries, model fallback and graceful failure |
