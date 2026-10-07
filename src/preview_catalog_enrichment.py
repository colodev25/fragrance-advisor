"""Preview a small enrichment sample; never writes catalog or index files."""
import argparse
import json

from src.catalog_integrity import CATALOG_PATH
from src.catalog_enrichment import EnrichmentBatch, enrich_catalog_fields
from src.ingest import KNOWN_FAMILIES, _get_groq_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--live", action="store_true", help="Make real Groq calls; default is a read-only sample listing")
    args = parser.parse_args()
    products = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    sample = [product for product in products if not product.get("family") or
              not all(product.get("olfactory_pyramid", {}).get(stage) for stage in ("top", "heart", "base"))][:args.limit]
    batch = EnrichmentBatch()
    client = _get_groq_client() if args.live else None
    if args.live and client is None:
        parser.error("GROQ_API_KEY richiesta per --live")
    for product in sample:
        report = {"id": product["id"], "name": product["name"]}
        if args.live:
            report["enrichment"] = enrich_catalog_fields(client, product["name"], product.get("brand", ""),
                product.get("description", ""), product.get("tags", []),
                product.get("olfactory_pyramid", {"top": [], "heart": [], "base": []}),
                product.get("family", ""), KNOWN_FAMILIES, batch)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.live:
        print(f"Richieste prodotto: {batch.requests}; fallimenti: {batch.failed}; rinviati: {batch.skipped}.")


if __name__ == "__main__":
    main()
