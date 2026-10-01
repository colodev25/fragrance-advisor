# Search engine

The search layer retrieves fragrance candidates from the catalog using ChromaDB vector search and applies deterministic price and lexical processing. It is implemented by `src/search.py`; `src/reindex.py` builds the persistent index from `data/catalog.json`.

## Indexing

Run:

```bash
python src/reindex.py
```

The reindexer recreates `chroma_db/`, creates the `fragrances` collection with cosine distance, and indexes each product's `semantic_text`. If that field is empty, it builds a shorter text from the product name, brand, family and description. ChromaDB's `DefaultEmbeddingFunction` produces embeddings locally; the search query uses the same default function.

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

For a full Shopify catalog refresh, first run `python src/ingest.py`, then run the reindexer. On API startup, a missing or empty `chroma_db/` directory triggers an automatic reindex attempt from the existing local catalog. If the catalog is unavailable or empty, index creation cannot complete.

## Component boundaries

The search engine returns candidates and metadata; it does not write conversational responses or manage sessions. `FragranceAdvisor` decides how the candidates fit the conversation and asks the configured Groq model to formulate the reply.
