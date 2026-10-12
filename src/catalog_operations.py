"""Commercial eligibility and operator-only catalog reports; no model calls."""
from collections import Counter
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path

try:
    from src.catalog_integrity import atomic_write_json, catalog_fingerprint
except ModuleNotFoundError:
    from catalog_integrity import atomic_write_json, catalog_fingerprint

KIT = re.compile(r"\b(?:kit|discovery\s+set|sample\s+set|gift\s+set|set\s+regalo|coffret|set\s+(?:di\s+)?campioni|campioni)\b", re.I)


def catalog_kind(product):
    if product.get("price") == 0:
        return "gift"
    text = " ".join([product.get("name", ""), product.get("shopify_product_type", ""), *product.get("tags", [])])
    if re.search(r"\b(?:omaggi\w*|free\s+gift|gift\s+with\s+purchase)\b", text, re.I):
        return "gift"
    return "kit" if KIT.search(text) else "perfume"


def requested_scope(query, previous="perfume"):
    match = KIT.search(query)
    if match:
        before = query[:match.start()].lower()
        return "perfume" if re.search(r"\b(?:non(?:\s+voglio)?|senza|evita)\s+(?:(?:un|i|dei)\s+)?$", before) else "kit"
    if re.search(r"\b(?:profumo|fragranza|bottiglia)\b", query, re.I):
        return "perfume"
    return previous


def quality(products):
    return {
        "products": len(products),
        "missing_family": sum(not(p.get("family") or (p.get("family_inference") or {}).get("value")) for p in products),
        "missing_notes": sum(not(any(p.get("olfactory_pyramid", {}).values()) or p.get("unpositioned_notes")) for p in products),
        "incomplete_pyramid": sum(not all(p.get("olfactory_pyramid", {}).get(k) for k in ("top", "heart", "base")) for p in products),
        "missing_image": sum(not p.get("urls", {}).get("image_url") for p in products),
        "missing_variant": sum(not p.get("variant_id") for p in products),
        "commercial_kinds": dict(Counter(catalog_kind(p) for p in products)),
    }


def sync_report(products, unavailable, dropped_count, previous, directory, now=None):
    now = now or datetime.now(timezone.utc)
    old = {p["id"]: p for p in previous}
    current = {p["id"]: p for p in products + unavailable}
    changes = {
        "added": len(current.keys() - old.keys()), "removed": len(old.keys() - current.keys()),
        "price_changed": sum(p.get("price") != old[i].get("price") for i, p in current.items() if i in old),
        "stock_changed": sum(p.get("in_stock") != old[i].get("in_stock") for i, p in current.items() if i in old),
    }
    warnings = []
    if old and len(current) < len(old) * 0.7:
        warnings.append("Product count decreased by more than 30%; operator review required.")
    old_available = sum(p.get("in_stock") is True for p in old.values())
    if old_available and len(products) < old_available * 0.7:
        warnings.append("Available product count decreased by more than 30%; review stock changes.")
    state_path = Path(directory) / "catalog_enrichment_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"queue": {}}
    return {"version": 1, "status": "success", "verified_at": now.isoformat(),
            "catalog_hash": catalog_fingerprint(products), "quality": quality(products),
            "out_of_stock": len(unavailable), "dropped": dropped_count, "changes": changes,
            "queue": dict(Counter(e["status"] for e in state["queue"].values())), "warnings": warnings}


def write_report(path, report):
    atomic_write_json(path, report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("\n## Catalog report\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n")
    if os.getenv("GITHUB_ACTIONS") == "true":
        for warning in report.get("warnings", []):
            print("::warning::" + warning)
