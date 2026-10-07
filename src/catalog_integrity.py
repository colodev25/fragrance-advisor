"""Catalog validation and atomic generation manifests."""
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = BASE_DIR / "data" / "catalog.json"
CHROMA_PATH = BASE_DIR / "chroma_db"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DOCUMENT_VERSION = 1
MANIFEST_VERSION = 1


def semantic_document(product):
    return product.get("semantic_text") or " ".join(
        product.get(key, "") for key in ("name", "brand", "family", "description")
    )


def validate_catalog(products):
    """Reject essential errors; warn about absent optional data."""
    if not isinstance(products, list) or not products:
        raise ValueError("Il catalogo deve essere una lista non vuota.")
    seen, warnings = set(), []
    for index, product in enumerate(products):
        if not isinstance(product, dict):
            raise ValueError(f"Prodotto {index}: record non valido.")
        identifier = product.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError(f"Prodotto {index}: ID mancante o duplicato.")
        seen.add(identifier)
        for key in ("name", "brand", "family", "ptype", "description", "semantic_text", "usage_profile"):
            if key in product and not isinstance(product[key], str):
                raise ValueError(f"{identifier}: {key} deve essere testo.")
        if not product.get("name", "").strip() or not (
            product.get("semantic_text", "").strip() or product.get("description", "").strip()
        ):
            raise ValueError(f"{identifier}: nome o descrizione mancanti.")
        price = product.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
            raise ValueError(f"{identifier}: prezzo non valido.")
        if product.get("in_stock") is not True:
            raise ValueError(f"{identifier}: prodotto non disponibile nel catalogo ricercabile.")
        urls = product.get("urls")
        if not isinstance(urls, dict):
            raise ValueError(f"{identifier}: collegamenti mancanti.")
        for key in ("product_page", "add_to_cart", "image_url"):
            value = urls.get(key, "")
            if key == "image_url" and not value:
                warnings.append(f"{identifier}: immagine assente.")
                continue
            if not isinstance(value, str):
                raise ValueError(f"{identifier}: {key} non valido.")
            try:
                parsed = urlsplit(value)
                valid = parsed.scheme in {"https", "http"} and bool(parsed.hostname)
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"{identifier}: {key} deve essere un URL HTTP(S) assoluto.")
        pyramid = product.get("olfactory_pyramid", {})
        if not isinstance(pyramid, dict):
            raise ValueError(f"{identifier}: piramide non valida.")
        for section in ("top", "heart", "base"):
            notes = pyramid.get(section, [])
            if not isinstance(notes, list) or any(not isinstance(note, str) or not note.strip() for note in notes):
                raise ValueError(f"{identifier}: note {section} non valide.")
        if not product.get("family"):
            warnings.append(f"{identifier}: famiglia assente.")
        if not any(pyramid.get(section) for section in ("top", "heart", "base")):
            warnings.append(f"{identifier}: note assenti.")
    return warnings


def catalog_fingerprint(products):
    canonical = json.dumps(sorted(products, key=lambda item: item["id"]),
                           sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_generation(root=CHROMA_PATH):
    root = Path(root)
    manifest = json.loads((root / "active.json").read_text(encoding="utf-8"))
    generation = manifest.get("generation", "")
    if not isinstance(generation, str) or len(generation) != 32 or any(c not in "0123456789abcdef" for c in generation):
        raise ValueError("Identificativo generazione non valido.")
    if (manifest.get("manifest_version") != MANIFEST_VERSION
            or manifest.get("document_version") != DOCUMENT_VERSION
            or manifest.get("embedding_model") != EMBEDDING_MODEL
            or manifest.get("collection") != f"fragrances_{generation}"):
        raise ValueError("Indice incompatibile: eseguire src/reindex.py prima dell'avvio.")
    products = json.loads((root / "generations" / f"{generation}.json").read_text(encoding="utf-8"))
    validate_catalog(products)
    if manifest.get("catalog_hash") != catalog_fingerprint(products) or manifest.get("product_count") != len(products):
        raise ValueError("Catalogo della generazione incoerente con l'indice.")
    return manifest, products
