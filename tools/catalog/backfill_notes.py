"""Preview or apply local narrative-note recovery; no Shopify/Groq calls."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ingest import refresh_declared_notes
from src.catalog_integrity import atomic_write_json, validate_catalog


def run(directory, apply=False):
    changes = 0
    pending = []
    for filename in ("catalog.json", "out_of_stock.json"):
        path = Path(directory) / filename
        if not path.exists():
            continue
        products = json.loads(path.read_text(encoding="utf-8"))
        # Validate unavailable records with their stock flag temporarily enabled.
        validate_catalog([dict(product, in_stock=True) for product in products])
        refreshed = [refresh_declared_notes(product) for product in products]
        validate_catalog([dict(product, in_stock=True) for product in refreshed])
        for before, after in zip(products, refreshed):
            added = [name for name in after.get("unpositioned_notes", [])
                     if name.casefold() not in {value.casefold() for value in before.get("unpositioned_notes", [])}]
            if added:
                changes += 1
                print(json.dumps({"id": after["id"], "name": after["name"], "added": added}, ensure_ascii=True))
        if refreshed != products:
            pending.append((path, refreshed))
    # Validate both files before writing either dataset.
    if apply:
        for path, refreshed in pending:
            atomic_write_json(path, refreshed)
    print(f"Products with recovered notes: {changes}; mode: {'apply' if apply else 'preview'}")
    return changes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write validated results; otherwise preview only.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    run(args.data_dir, args.apply)
