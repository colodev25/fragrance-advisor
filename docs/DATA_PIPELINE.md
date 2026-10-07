# Catalog data pipeline

The ingestion code in `src/ingest.py` downloads products from a Shopify store's public `/products.json` endpoint, normalizes fragrance information and writes JSON datasets under `data/`. The vector index is a separate derived artifact created by `src/reindex.py`.

```text
Shopify /products → ingest.py → data/catalog.json
                                data/out_of_stock.json
                                data/scartati.json
                                             │
                                             ▼
                                        reindex.py
                                             │
                                             ▼
                                      chroma_db/
```

## Ingestion

Run the pipeline from the repository root:

```bash
python src/ingest.py
```

The store URL is read from `SHOPIFY_STORE_URL`. The script loads a root `.env` file for local use; alternatively, set the environment variable in the process environment. The ingestion client paginates through the Shopify JSON products endpoint and filters product types and keywords to focus on fragrances.

The transformation extracts or derives product name, brand, SKU, price, currency, availability, tags, fragrance family, product type, usage profile, description, olfactory pyramid, URLs and semantic text. HTML sections are used first; regex fills only empty pyramid sections, and recognized tags supply a missing family. Set `GROQ_API_KEY` to enable grounded LLM enrichment for remaining gaps, including partial pyramids.

## Grounded enrichment

`src/catalog_enrichment.py` sends description, tags and existing fields to the model configured by `GROQ_CATALOG_MODEL` (default `openai/gpt-oss-20b`). Every accepted note must occur in a quoted source excerpt. A pyramid position requires a matching explicit stage cue; ambiguous or unpositioned mentions go to `unpositioned_notes`. Existing sections and explicit family values are preserved. Source quotes establish traceability, not an absolute guarantee of semantic accuracy.

An explicit family recovered from the source populates `family`. A model classification based on the described accords is stored separately in `family_inference`, with evidence and `kind: inferred`. The search document labels it as a suggested classification; deterministic family filters continue to use the explicit `family` field. `data_provenance` records HTML, tag, regex and LLM origins, including individual LLM note evidence.

Missing notes never generate generic citrus/floral/woody defaults. Unpositioned supported notes are included in the semantic document and advisor note vocabulary. Existing catalogs remain compatible, but the new fields and clean search documents appear only after ingestion, reindexing and backend restart.

Enrichment runs during ingestion, not customer requests. It uses a bounded description (6,000 characters), up to 100 tags and a 20-second client timeout. GPT-OSS models use `reasoning_effort: low`; the configurable `GROQ_CATALOG_MAX_TOKENS` defaults to 2,048 (allowed range 512–8,192). Catalog extraction never automatically doubles this budget after truncation. Validate settings on a small sample before increasing them.

Each product request can retry a transient error once. Numeric or HTTP-date `Retry-After` headers are respected, with a maximum inline wait of 30 seconds. Longer rate-limit delays suspend enrichment for this ingestion instead of retrying early. The batch spaces product requests using `GROQ_CATALOG_INTERVAL_SECONDS` (default 2, range 0–30); after an exhausted rate-limit retry it also applies the supplied cooldown, or 15 seconds when absent. Three consecutive failed product requests, authentication/configuration errors, or a long rate-limit delay suspend further LLM requests. Deterministic extraction and valid cached results continue. Logs distinguish rate limits, timeouts, connection/server errors, truncated/empty answers and invalid responses; provider bodies are not logged.

Successful supported results, including valid empty results, are stored in each product's `enrichment_cache`. Subsequent ingestion loads cache from both availability datasets and revalidates evidence before reuse. The signature includes name, brand, bounded description/tags, deterministic pyramid/family, model, token budget and extraction policy version. Price and stock changes do not invalidate extraction; source or policy changes do. Failed results are not cached. Existing records without this cache need one successful extraction before reuse is possible. The summary reports requests per product (retries excluded), cache reuse, failures and deferred products.

## Small preview

```bash
python -m src.preview_catalog_enrichment --limit 3
python -m src.preview_catalog_enrichment --limit 3 --live
```

The first command only lists incomplete products from the existing local catalog. `--live` enables real Groq calls and prints supported results for up to ten products. Neither command downloads Shopify data, writes datasets or changes the active index. This is a preview of supplied catalog descriptions/tags, not a full ingestion or a quality guarantee for the entire catalog. After evaluating it, run ingestion, reindexing and restart as usual.

## Output datasets

| File                     | Contents                                                                                      |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| `data/catalog.json`      | Products considered available and eligible for recommendations.                               |
| `data/out_of_stock.json` | Eligible fragrance products that are currently unavailable.                                   |
| `data/scartati.json`     | Products excluded from the searchable catalog during processing. This file is ignored by Git. |

The catalog is the source of truth for runtime search. Product identifiers are derived from Shopify IDs, and product records contain `semantic_text` for indexing.

## Rebuild the search index

After ingestion, rebuild the persistent ChromaDB collection:

```bash
python src/reindex.py
```

Run the two stages in sequence for a complete local refresh:

```bash
python src/ingest.py
python src/reindex.py
```

The reindexer validates `data/catalog.json`, builds a new collection and activates its catalog snapshot only after verification. It preserves existing collections and snapshots; the API does not rebuild at startup. Restart the backend to load the new generation. See [index operations](INDEX_OPERATIONS.md).

## Automated synchronization

`.github/workflows/catalog-sync.yml` runs every two days or through manual dispatch, with concurrent runs serialized. It uses `SHOPIFY_STORE_URL` and optional `GROQ_API_KEY` repository secrets and commits changes to `catalog.json` or `out_of_stock.json` on `feature/new-site`. `scartati.json` remains a local report excluded from Git. The workflow does not publish ChromaDB: Render builds the index during deployment. Shopify pagination errors or invalid/empty searchable catalogs fail the import; each JSON file is replaced atomically, with the primary catalog written last. The three reports are not a single transactional bundle.
