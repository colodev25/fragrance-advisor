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

The transformation extracts or derives product name, brand, SKU, price, currency, availability, tags, fragrance family, product type, usage profile, description, olfactory pyramid, URLs and semantic text. It cleans HTML and note descriptions; it can use Groq as a fallback for extracting the olfactory pyramid when the structured product content does not provide it. Set `GROQ_API_KEY` to enable this fallback.

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
