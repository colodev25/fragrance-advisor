# Catalog and index operations

## Update lifecycle

1. `python src/ingest.py` downloads the complete Shopify catalog and validates available fragrances before replacing `data/catalog.json`.
2. `python src/reindex.py` validates the source, creates a unique collection, checks product IDs/count and executes a local search probe.
3. The builder writes the catalog snapshot and manifest under `chroma_db/generations/`, then atomically replaces `chroma_db/active.json`.
4. Restart the backend to load the selected generation. Running processes keep their previously loaded catalog and collection.

Essential errors (empty catalog, missing/duplicate IDs, invalid prices, unavailable products, malformed notes or required links) stop the update. Missing family, notes or image produce warnings. The builder records a SHA-256 catalog fingerprint, product count, generation ID, embedding model, document version and UTC timestamp. Product/key order does not affect the fingerprint.

At startup, search verifies snapshot integrity, model/version compatibility and collection IDs/count. Advisor keyword searches and card enrichment use the same snapshot. A different `data/catalog.json` is reported as pending; the valid active generation continues to serve. `/health` reports `503` if no valid generation can be loaded.

## Migration and failure recovery

The legacy `fragrances` collection has no generation manifest and cannot satisfy the new startup checks. Run the updated reindexer once before starting the updated backend. It preserves the legacy collection.

Failed indexing never changes `active.json`; existing catalog snapshots and collections remain available. Retry after fixing the reported error. Empty source catalogs are rejected to prevent accidental publication of an empty search index.

Each successful generation has `<generation>.json` and `<generation>.manifest.json` files. For a manual rollback, stop the service, replace `active.json` with the manifest of a previous compatible generation whose snapshot and collection still exist, then restart. Startup verifies the restored generation. Changing embedding/document versions requires rebuilding rather than restoring an incompatible generation.

A `chroma_db/reindex.lock` file prevents concurrent builders. Normal completion or exceptions release it. A forcibly terminated process can leave the lock behind: confirm that no builder is running before removing that lock and retrying. Old or failed collections are retained deliberately; clean them only during maintenance, after ensuring no running process uses them. Repeated local rebuilds consume additional disk space.

## Render deployment

Build Command:

```sh
pip install -r requirements.txt && python src/reindex.py
```

Start Command:

```sh
uvicorn src.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Health Check Path: `/health`.

The build must produce `chroma_db/` in the filesystem delivered to the running service. A persistent disk mounted at that location requires checking build/runtime disk access before adopting this setup. No Render disk configuration is tracked in this repository. Generation retention only applies where the same index filesystem is retained; it does not guarantee history across fresh deployments.

Render checks HTTP readiness during deployments and while instances run. The endpoint returns `200` when the advisor initialized and `503` otherwise. It does not call Groq or execute an embedding search on each check, and does not continuously diagnose those dependencies. It does not prevent free-plan cold starts. See [Render health checks](https://render.com/docs/health-checks).

Catalog synchronization commits do not upload an index. Ensure Render deploys the updated commit through its configured deployment mechanism. The synchronization workflow uses the GitHub Actions token; its push does not automatically trigger another Actions workflow. The test workflow independently builds an index before running tests.
