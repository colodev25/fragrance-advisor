# Search engine

The search layer retrieves fragrance candidates from the catalog using ChromaDB vector search and applies deterministic price and lexical processing. It is implemented by `src/search.py`; `src/reindex.py` builds the persistent index from `data/catalog.json`.

## Indexing

Run:

```bash
python src/reindex.py
```

The reindexer creates a new `fragrances_<generation>` collection with cosine distance and indexes each product's `semantic_text`, falling back to name, brand, family and description. ChromaDB's `DefaultEmbeddingFunction` produces embeddings locally. The active manifest records the embedding model and document format version; search checks compatibility and uses the matching catalog snapshot. Existing collections are preserved.

Each record stores the catalog identifier, semantic text and metadata used by the application, including name, brand, price, family, product type, stock status, product URL, cart URL and image URL.

## Runtime retrieval

For each query, `FragranceSearchEngine.search()`:

1. Builds ChromaDB price filters from optional minimum and maximum values.
2. Retrieves a bounded pool: at least ten where available, expanding with the requested result count up to 100 records. The advisor requests 40 for ranking.
3. Extracts keywords from the query and keeps candidates whose indexed document contains at least one keyword.
4. Applies the requested result limit.

If keyword matching produces no candidates, the search layer returns the semantically retrieved records that satisfy the price constraints. The result includes IDs, metadata, documents and an `exact_match_found` flag; this flag indicates whether the lexical pass found matches, not whether the results are exact product matches.

## Notes and product constraints

The advisor and `src/recommendation_preferences.py` check stock, price, note requirements/exclusions and product suitability against the verified catalog snapshot. They check the full catalog, so a valid candidate outside the semantic pool can still be offered. Semantic retrieval orders the admitted candidates; its `exact_match_found` flag is not proof that customer constraints were satisfied. Excluded notes are removed from the ranking query. See [preference policy](ADVISOR.md#preference-policy).

## Refreshing the index

After changing the catalog, regenerate the index:

```bash
python src/reindex.py
```

For a full refresh, run `python src/ingest.py`, then the reindexer, then restart the backend. The API never rebuilds its index at startup. A missing or incompatible active generation prevents readiness; an updated source catalog alone does not change the running generation. See [index operations](INDEX_OPERATIONS.md) for validation, migration and recovery.

## Component boundaries

The search engine returns candidates and metadata; it does not write conversational responses or manage sessions. `FragranceAdvisor` decides how the candidates fit the conversation and asks the configured Groq model to formulate the reply.
