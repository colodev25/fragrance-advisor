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

### Product identity and clarification

`src/product_identity.py` prepares catalog name aliases and matching patterns at startup. Complete and more specific names take precedence over nested shorter names. Matching normalizes case, accents and punctuation, accepts common concentration abbreviations and uses the declared brand, concentration and title size to distinguish records. Names and catalog IDs remain separate: a named-product switch and later follow-ups use the ID, including when two brands share a title.

An ambiguous reference receives a local clarification with no product cards, search or model call. Up to five existing quick-reply buttons show the brand and full title. More candidates require a narrower brand, concentration or format. Identical normalized visible identities are not resolved using arbitrary numbered buttons. High-confidence spelling suggestions are offered only for explicit information requests and always require confirmation.

SQLite `guided_state.pending_product_choice` retains the original request, candidate IDs and visible-label mapping. Choosing a button or supplying a distinguishing hint resumes the original intent and budget; navigation and advisor restart preserve this state. A clear new search or conversation restart retires the pending choice. Failed processing retains the pending state, and identified-request recovery follows the existing atomic receipt contract. A removed or unavailable chosen ID is never substituted with another record.

An explicitly requested concentration or size without a verified matching record receives clarification rather than a silent fallback. Size evidence comes from the product title: tags may list several Shopify variants and do not prove which variant supplies the stored price or purchase link. Selecting variants within one Shopify product remains a separate cart/integration concern. These rules are deterministic and do not interpret every possible natural-language spelling or comparison.

For a request that needs product recommendations, the advisor:

1. Updates the session's recognized preferences, requested notes, exclusions and price constraints.
2. Checks admission across the complete loaded catalog, then retrieves semantic ranking through `FragranceSearchEngine`.
3. Prioritizes confirmed matches and enriches admitted cards by stable catalog ID.
4. Sends the request and selected catalog context to Groq to produce the conversational explanation.
5. Stores the answer, active product and guided-flow state in `SessionStore`.

The model explains and contextualizes catalog candidates. Product details shown in cards come from the catalog, and the advisor can return no product when the available candidates do not fit the request.

Free-search and alternative recommendations require a JSON object with `selection` (a supplied candidate ID, or `null`) and a non-empty `reply`. Invalid JSON, unknown IDs and missing fields trigger the fallback model. If no valid selection is available within the request budget, the API returns a retryable `503`; conversation state and the previous active fragrance remain unchanged. An explicit `null` selection clears the active fragrance. No product is inferred from its name or selected automatically from the first search result.

## Preference policy

`src/recommendation_preferences.py` applies the same balanced policy to guided and free recommendations:

| Criterion | Treatment |
| --- | --- |
| Availability and numeric budget | Required. The smaller of the textual ceiling and API ceiling applies; conflicting bounds request clarification. |
| Recognized requested notes | Required evidence from declared notes, unpositioned notes, relevant note tags or positive description mentions. “Iris e vaniglia” requires both; “iris o vaniglia” permits either. |
| Excluded notes or families | Required. A forbidden declared note/family is never relaxed. Note exclusions reject products without usable note evidence; family exclusions reject products without a declared family. |
| Family, recipient, season and occasion | Preferences by default. Confirmed matches are prioritized. “Solo”, “deve” and similar recognized markers make the supplied criteria required. |

When confirmed matches exist, return up to three guided cards or a free-search shortlist without padding it with partial matches. If none exist, admitted alternatives may be offered with a deterministic notice explaining their differences. The model receives only admitted candidates and cannot choose a rejected product ID.

The parser handles common Italian expressions and catalog note names, with common English note aliases. Longest note matches preserve distinctions such as rose versus pink pepper. Unknown explicit note requests/exclusions request clarification instead of being silently dropped. Interpretation is rule based and does not cover arbitrary natural-language constructions.

Unknown recipient or season is kept unknown. Season estimates based on family remain internally distinct and do not count as confirmed seasonal matches. Product-card season labels omit the derivation suffix; partial recommendation notices still explain relevant differences. Generic “caldo” or “versatile” does not establish summer or year-round suitability. Explicit tags and usage information take precedence over family estimates; inferred family classifications remain distinct from declarations.

Preference profiles are stored inside SQLite `guided_state.preferences`. A cheaper alternative retains note exclusions, requested notes and other preferences. Explicit replacements update the relevant criteria; “nessun limite di budget” removes textual bounds, “nessuna esclusione” clears exclusions, and “nessuna nota obbligatoria” clears required notes. The latest supplied API ceiling is retained separately until replaced by another API value or session reset. Restarting the guided consultation clears the preference profile; switching to free chat preserves it. Guided budget clarification retains the previous answers; unresolved note constraints remain pending across the quiz rather than disappearing at the next step.

Price boundaries use cents: “sotto 120€” means at most 119.99€, “massimo 120€” permits 120€, and “oltre 200€” begins at 200.01€. Informational questions about a named product can show its actual price; recommendation requests referencing that product still apply the constraints. A named reference in an alternative search is excluded from the results.

Note admission reflects the available olfactory catalog data; it does not certify formula composition or ingredient absence. Each exclusion-based selection includes a short explanation of this catalog basis. Evidence is prepared at advisor startup and reused; admission adds no LLM call. Impossible constraints are answered locally without embedding or model work.

## Product card details

`_enrich_product_payload` takes the complete `olfactory_pyramid` and `unpositioned_notes` from the matched catalog record. It removes blank entries and repeated spellings without assigning a stage to an unpositioned note. Notes repeated across explicitly declared stages remain in those stages. Additional notes already present anywhere in the pyramid are omitted from the separate list. `key_notes` remains a short preview; a missing note list is not replaced with family names.

Both card types carry these fields. The widget shows the pyramid and a separate additional-note section in its detail panel. This presentation uses the existing catalog data and adds no model work or index rebuild requirement. Old persisted cards without the fields retain a neutral summary until new responses provide structured details.

The displayed `ptype` and first profile item contain only the concentration/type. Compound source text such as “Eau de parfum, unisex” becomes “Eau de Parfum”; the original type text remains available as recipient evidence when preparing the separate recipient item. The customer season label contains no “(dedotta)” suffix. Deterministic recommendation checks still retain declared/inferred evidence separately.

The local DevTools snippet uses the remote Render API, not the local Python files. Deploying the updated backend is required for new responses to carry the full note fields. Saved cards and cached responses from the previous backend contain only the old summary and cannot reconstruct a stage. After deploying and publishing the widget, start a new conversation for new structured cards. The widget also cleans type and season text in older received or saved profiles.

## Session state

Each `session_id` stores:

- Conversation history
- The active fragrance, if one is selected
- Guided-flow step and collected answers
- Last update time, inactivity deadline, session token and revision, and the SHA-256 hash of the private session credential

`SessionStore` reloads persisted state for each request. Conversation continuity after a restart requires the SQLite file to survive; the current Render Free filesystem is ephemeral. Session IDs are mandatory and the shared `default` value is rejected. `POST /reset` clears the session only with its matching `session_key`. The advisor checks this credential before state loading or cached-result recovery; new messages in an established session also require the current context. A failed first message leaves an owned, expiring empty claim so it can be retried safely. Existing sessions without an owner hash cannot be adopted.

New completed messages renew a 24-hour inactivity deadline; reads, failed processing and cached retries do not. Expiry and supplied token/revision checks run before model work. The API starts maintenance at startup and hourly, in batches of 100 expired sessions and at most 10 batches per cycle. Cleanup uses the same session locks, skips busy conversations and deletes state and receipts together. SQLite connections close after every operation, including failures. Inactive customer copies are removed from the advisor's RAM maps after each request.

Before processing an uncached message, the active fragrance is refreshed from the currently loaded catalog by stable product ID, including its price, links and olfactory data. Legacy records without an ID use only a unique name/brand match. A removed or unavailable product is cleared; a follow-up receives an availability notice and an invitation to search again. Explicit new searches can proceed normally. This uses the verified runtime snapshot, not a live Shopify inventory lookup.

`src/conversation_requests.py` coordinates the complete load/process/save operation and reset with a lock per session. Waiting requests keep a reference to that lock; unused locks are removed. This coordination assumes the current deployment with one worker and one service instance.

An optional `request_id` identifies one message. Before processing, the advisor checks its saved result and payload fingerprint. A matching completed request returns the saved response; conflicting input is rejected. New results are saved atomically with session state. Transient LLM failures return `503` without committing state or a completed result. A guided selection with valid cards and a fixed introduction is a completed `200` result. SQLite retains 100 complete responses per session and fingerprints for older identifiers, until reset or session cleanup. See [API retry semantics](API.md#identified-requests-and-retries).

The advisor retains at most 40 recent history messages (20 complete exchanges) when loading and saving a conversation. Active fragrance and guided preferences are stored separately. This limit concerns backend conversation state; widget history is managed by the frontend.

## LLM resilience

`src/chat_budget.py` gives each chat request a shared 25-second processing budget and at most three Groq calls, including intent classification, retries and model fallback. The budget starts before waiting for the session lock. SDK retries are disabled; only the application decides whether another call is allowed. Models remain configurable with `GROQ_PRIMARY_MODEL` and `GROQ_FALLBACK_MODEL`.

| Task | Per-call timeout | Completion token ceiling |
| --- | --- | --- |
| Ambiguous intent classification | 3 seconds; one call | 768 |
| Guided selection introduction | 10 seconds | 1,024 |
| Product explanation, follow-up or JSON selection | 10 seconds | 2,048 |

GPT-OSS calls use `reasoning_effort: low`. Completion allowances cover generated reasoning and visible output; input tokens also consume the provider quota. Empty, truncated and invalid selections are rejected without doubling the token allowance. Each next call receives the smaller of its task timeout and the remaining shared budget. Fallback alternates the primary and reserve models when available. Transient errors permit an inline wait of at most one second; a longer `Retry-After` ends automatic attempts and is forwarded to the browser.

These are cooperative limits: SDK timeouts apply to network operations, and a synchronous call or local database/search operation already underway can exceed the overall target. The session lock remains held until processing actually stops; no detached worker may later commit a failed request. Deadline checks run before further model work and before saving the result. Render startup and API thread-pool queueing precede this processing budget.

Model context includes the latest two history messages, limited to 2,000 characters each, and product documents limited to 1,800 characters, prioritizing note/family/use lines. Each message sent to the model is capped at 16,000 characters. Current customer input and catalog selection identifiers remain part of the prompt; recommendation rules are unchanged. These character and completion limits contain consumption but do not guarantee that shared free-plan quotas will remain available.

Exhausted attempts, invalid answers or expired processing return a structured `503`, without saving a retry message as a completed conversation. The same request identifier can therefore recover after a temporary failure. Guided recommendations may use a fixed introduction when their cards are already valid and the processing deadline has not expired. Intent classification can default to continuing the active-product discussion. Internal reasoning and provider error bodies are never exposed.

Catalog enrichment uses the separate existing policy in `src/catalog_enrichment.py`: its nightly pacing, token reservations, callbacks and deferred retries remain independent of the chat budget.

## Responsibilities

| Component | Role |
| --- | --- |
| `src/main.py` | HTTP request handling and application startup |
| `src/advisor.py` | Conversation flow, candidate selection and response orchestration |
| `src/search.py` | ChromaDB retrieval and post-retrieval filtering |
| `src/session_store.py` | SQLite session persistence |
| `src/llm_resilience.py` | Groq attempts, validation and model fallback |
| `src/chat_budget.py` | Per-request processing deadline and call allowance |
