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

The transformation extracts or derives product name, brand, SKU, price, currency, availability, tags, fragrance family, product type, usage profile, description, olfactory pyramid, URLs and semantic text. HTML sections are used first; regex fills only empty pyramid sections, and recognized tags supply a missing family. `run_ingest` never calls Groq, even when an API key is present. Validated cached enrichment is preserved across price changes and transitions out of stock and back into stock. Remaining gaps enter a persistent queue for separate nightly processing.

## Grounded enrichment

`src/catalog_enrichment.py` sends description, tags and existing fields to the model configured by `GROQ_CATALOG_MODEL` (default `openai/gpt-oss-20b`). Every accepted note must occur in a quoted source excerpt. A pyramid position requires a matching explicit stage cue; ambiguous or unpositioned mentions go to `unpositioned_notes`. Existing sections and explicit family values are preserved. Source quotes establish traceability, not an absolute guarantee of semantic accuracy.

An explicit family recovered from the source populates `family`. A model classification based on the described accords is stored separately in `family_inference`, with evidence and `kind: inferred`. The search document labels it as a suggested classification; deterministic family filters continue to use the explicit `family` field. `data_provenance` records HTML, tag, regex and LLM origins, including individual LLM note evidence.

Missing notes never generate generic citrus/floral/woody defaults. Unpositioned supported notes are included in the semantic document and advisor note vocabulary. Existing catalogs remain compatible, but the new fields and clean search documents appear only after ingestion, reindexing and backend restart.

Enrichment runs separately through `src/catalog_jobs.py`. It uses a bounded description (6,000 characters), up to 100 relevant tags and a 20-second client timeout. GPT-OSS models use `reasoning_effort: low`; the configurable `GROQ_CATALOG_MAX_TOKENS` defaults to 2,048 (allowed range 512–8,192). Catalog extraction never automatically doubles this budget after truncation. The nightly workflow fixes the completion allowance at 2,048.

Each product request can retry a transient error once. Numeric or HTTP-date `Retry-After` headers are respected, with a maximum inline wait of 30 seconds. Longer delays, three consecutive failed products or authentication/configuration errors suspend the batch. Nightly request pacing and persistent reservations apply before every API call, including retries. Failed products keep their original data and retry on later nights. Logs distinguish rate limits, timeouts, connection/server errors, truncated/empty answers and invalid responses; provider bodies are not logged.

Successful supported results, including valid empty results, are stored in each product's `enrichment_cache`. Subsequent ingestion loads cache from both availability datasets and revalidates evidence before reuse. The signature includes name, brand, bounded description/tags, deterministic pyramid/family, model, completion budget and extraction policy version. Price and stock changes do not invalidate extraction; source or policy changes do. Recognized discount, price, size and stock tags are excluded from the extraction signature; other tag changes can invalidate it. Failed results are not cached. A policy change can require a fresh extraction of previously enriched products.

## Persistent queue and nightly budget

Each synchronized product stores `enrichment_input`: source description, relevant tags and deterministic fields before LLM extraction. `data/catalog_enrichment_state.json` tracks queue status, retry dates and token reservations. Deleted products leave the queue; unavailable products are skipped while their cache remains available. Legacy products without `enrichment_input` wait for the first synchronization.

```bash
python -m src.catalog_jobs --max-products 30 --token-budget 40000 --max-minutes 20
```

Only incomplete available products whose retry date is due can call Groq. `GROQ_API_KEY` is required when work is available. Untouched products take priority over failures, which rotate through the queue and retry after 1, 2, 4 and then 7 days, or a longer provider cooldown. Valid empty results finish processing until source or policy changes. Successful products are saved individually.

The limits are ceilings, not a promise to complete 30 products:

- At most 30 product attempts and 20 minutes per run.
- At most 40,000 conservatively reserved tokens in a rolling 24-hour window, retained across manual reruns.
- Pacing targets 4,000 reserved tokens per minute and checks an 8,000-token rolling minute allowance.
- Reservations use a conservative UTF-8 byte estimate of the prompt plus the completion allowance, including reasoning. Failed calls and retries retain their reservations; reported actual usage is recorded separately.
- Inputs whose conservative estimate exceeds 8,000 tokens are marked `needs_review` without calling the provider.

The initial backlog drains over successive nights; routine price and stock updates require no LLM work. The ledger covers catalog jobs only: customer conversations or other applications on the same account can still cause Groq rate limits. Those limits defer enrichment without blocking Shopify synchronization or the existing catalog.

Local checkpoint writes are atomic. GitHub publishes progress after processing, including ordinary failures. A forcibly terminated runner or a failed Git push can lose unpublished checkpoints; inspect failed runs before manually repeating them. Do not delete the state file to reset the budget or run local synchronization and enrichment concurrently against the same data directory.

## Small preview

```bash
python -m src.preview_catalog_enrichment --limit 3
python -m src.preview_catalog_enrichment --limit 3 --live
```

The first command only lists incomplete products from the existing local catalog. `--live` enables real Groq calls and prints supported results for up to ten products. Neither command downloads Shopify data, writes datasets or changes the active index. Preview calls do not use the nightly ledger and consume the same provider quota. After evaluating it, run synchronization, optional nightly enrichment, reindexing and restart.

## Output datasets

| File                     | Contents                                                                                      |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| `data/catalog.json`      | Products considered available and eligible for recommendations.                               |
| `data/out_of_stock.json` | Eligible fragrance products that are currently unavailable.                                   |
| `data/catalog_enrichment_state.json` | Persistent queue, retry dates and token reservations. |
| `data/scartati.json`     | Products excluded from the searchable catalog during processing. This file is ignored by Git. |

The catalog is the source of truth for runtime search. Product identifiers are derived from Shopify IDs, and product records contain `semantic_text` for indexing.

## Rebuild the search index

After ingestion, rebuild the persistent ChromaDB collection:

```bash
python src/reindex.py
```

Run synchronization and indexing in sequence for a local refresh. Optionally run `python -m src.catalog_jobs` between them to enrich due products; commercial updates do not depend on enrichment:

```bash
python src/ingest.py
python src/reindex.py
```

The reindexer validates `data/catalog.json`, builds a new collection and activates its catalog snapshot only after verification. It preserves existing collections and snapshots; the API does not rebuild at startup. Restart the backend to load the new generation. See [index operations](INDEX_OPERATIONS.md).

## Automated synchronization

| Workflow | Schedule (UTC) | Secret |
| --- | --- | --- |
| `catalog-sync.yml` | `0 3 */2 * *`: 03:00 on alternating days of the month | `SHOPIFY_STORE_URL` |
| `catalog-enrich.yml` | `35 3 * * *`: daily at 03:35 | `GROQ_API_KEY` |

Both support manual dispatch and share a concurrency group to prevent overlapping writes. They check out and publish catalog/queue changes to `feature/new-site`. In Italy, these schedules correspond to 04:00/04:35 in winter and 05:00/05:35 in summer. Scheduled workflows must also exist on the repository's default branch; checking out another branch inside a job does not activate its schedule.

`scartati.json` remains a local report excluded from Git. Neither workflow publishes ChromaDB: Render builds the index during deployment. A commit containing only queue progress may also trigger deployment, depending on Render's build filters; excluding `data/catalog_enrichment_state.json` from deployment triggers can avoid unnecessary rebuilds. Shopify pagination errors or invalid/empty searchable catalogs fail the import; files are replaced atomically, with the primary catalog written after the other reports and before the queue. These writes are not a single transaction: rerunning synchronization or the nightly job reconciles the queue from the datasets.
