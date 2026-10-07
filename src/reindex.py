"""Build and verify a new ChromaDB generation before atomic activation."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

try:
    from src.catalog_integrity import (CATALOG_PATH, CHROMA_PATH, DOCUMENT_VERSION,
        EMBEDDING_MODEL, MANIFEST_VERSION, atomic_write_json, catalog_fingerprint,
        semantic_document, validate_catalog)
except ModuleNotFoundError:
    from catalog_integrity import (CATALOG_PATH, CHROMA_PATH, DOCUMENT_VERSION,
        EMBEDDING_MODEL, MANIFEST_VERSION, atomic_write_json, catalog_fingerprint,
        semantic_document, validate_catalog)

DATA_PATH = CATALOG_PATH


def build_index(catalog_path=DATA_PATH, chroma_path=CHROMA_PATH, client_factory=None, embedding_factory=None):
    products = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    for warning in validate_catalog(products):
        print(f"[!] {warning}")
    root = Path(chroma_path)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "reindex.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(datetime.now(timezone.utc).isoformat())
    try:
        generation = uuid.uuid4().hex
        client = (client_factory or chromadb.PersistentClient)(path=str(root))
        embedding = (embedding_factory or embedding_functions.DefaultEmbeddingFunction)()
        name = f"fragrances_{generation}"
        collection = client.create_collection(name=name, embedding_function=embedding,
                                              metadata={"hnsw:space": "cosine"})
        ids = [product["id"] for product in products]
        documents = [semantic_document(product) for product in products]
        metadata = [{
            "name": product["name"], "brand": product.get("brand", ""),
            "price": float(product["price"]), "family": product.get("family", ""),
            "ptype": product.get("ptype", ""), "in_stock": True,
            "add_to_cart_url": product["urls"]["add_to_cart"],
            "product_page_url": product["urls"]["product_page"],
            "image_url": product["urls"].get("image_url", ""),
        } for product in products]
        for start in range(0, len(products), 50):
            collection.add(ids=ids[start:start + 50], documents=documents[start:start + 50],
                           metadatas=metadata[start:start + 50])
        if collection.count() != len(products) or set(collection.get(include=[])["ids"]) != set(ids):
            raise RuntimeError("Indice incompleto: la generazione precedente resta attiva.")
        probe = collection.query(query_texts=[documents[0]], n_results=1)
        if not probe.get("ids") or not probe["ids"][0] or probe["ids"][0][0] not in ids:
            raise RuntimeError("Verifica ricerca fallita: indice non attivato.")
        manifest = {
            "manifest_version": MANIFEST_VERSION, "generation": generation,
            "collection": name, "catalog_hash": catalog_fingerprint(products),
            "product_count": len(products), "embedding_model": EMBEDDING_MODEL,
            "document_version": DOCUMENT_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_json(root / "generations" / f"{generation}.json", products)
        atomic_write_json(root / "generations" / f"{generation}.manifest.json", manifest)
        atomic_write_json(root / "active.json", manifest)
        print(f"[+] Attivata generazione {generation}: {len(products)} prodotti.")
        return manifest
    finally:
        lock.unlink()


def main():
    build_index()


if __name__ == "__main__":
    main()
