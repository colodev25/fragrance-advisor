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
2. Retrieves up to ten semantically similar records, or fewer if the collection is smaller.
3. Extracts keywords from the query and keeps candidates whose indexed document contains at least one keyword.
4. Applies the requested result limit.

If keyword matching produces no candidates, the search layer returns the semantically retrieved records that satisfy the price constraints. The result includes IDs, metadata, documents and an `exact_match_found` flag; this flag indicates whether the lexical pass found matches, not whether the results are exact product matches.

## Notes and product constraints

The advisor also performs request-specific processing beyond the search engine, including explicit fragrance-note matching and product suitability checks. Those rules live in `src/advisor.py`; they are not all implemented as ChromaDB filters. The search layer applies numeric price limits but does not independently guarantee stock availability filtering at query time. The catalog ingestion step controls which products are written to the primary searchable catalog.

## Refreshing the index

After changing the catalog, regenerate the index:

```bash
python src/reindex.py
```

For a full refresh, run `python src/ingest.py`, then the reindexer, then restart the backend. The API never rebuilds its index at startup. A missing or incompatible active generation prevents readiness; an updated source catalog alone does not change the running generation. See [index operations](INDEX_OPERATIONS.md) for validation, migration and recovery.

## Component boundaries

The search engine returns candidates and metadata; it does not write conversational responses or manage sessions. `FragranceAdvisor` decides how the candidates fit the conversation and asks the configured Groq model to formulate the reply.
