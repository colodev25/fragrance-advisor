"""
reindex.py - Rigenerazione e sincronizzazione del Database Vettoriale ChromaDB

Legge il file data/catalog.json (aggiornato e contenente solo prodotti in-stock)
e ricostruisce da zero la collection 'fragrances' in ChromaDB.

Uso:
    python src/reindex.py
"""

import json
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = BASE_DIR / "data" / "catalog.json"
CHROMA_DIR = BASE_DIR / "chroma_db"
COLLECTION_NAME = "fragrances"


def main():
    print("=== AVVIO RE-INDICIZZAZIONE CHROMADB ===")

    if not CATALOG_PATH.exists():
        print(f"[!] Errore: File {CATALOG_PATH} non trovato. Esegui prima 'python src/ingest.py'.")
        return

    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    print(f"[*] Caricati {len(catalog)} profumi da catalog.json.")

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Reset completo della collection per evitare record obsoleti
    existing_collections = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing_collections:
        print(f"[*] Eliminazione vecchia collection '{COLLECTION_NAME}'...")
        client.delete_collection(COLLECTION_NAME)

    embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"}
    )
    print(f"[*] Creata nuova collection '{COLLECTION_NAME}'.")

    ids = []
    documents = []
    metadatas = []

    for item in catalog:
        doc_id = str(item.get("id"))
        semantic_text = item.get("semantic_text") or item.get("description") or item.get("name")

        meta = {
            "name": str(item.get("name", "")),
            "brand": str(item.get("brand", "Profumeria Artistica")),
            "price": float(item.get("price", 0.0) or 0.0),
            "family": str(item.get("family", "")),
            "ptype": str(item.get("ptype", "")),
            "add_to_cart_url": str(item.get("urls", {}).get("add_to_cart", "")),
            "product_page_url": str(item.get("urls", {}).get("product_page", "")),
            "image_url": str(item.get("urls", {}).get("image_url", ""))
        }

        ids.append(doc_id)
        documents.append(semantic_text)
        metadatas.append(meta)

    # Inserimento a blocchi (batch)
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        end = min(i + batch_size, len(ids))
        collection.add(
            ids=ids[i:end],
            documents=documents[i:end],
            metadatas=metadatas[i:end]
        )
        print(f"    Indicizzati {end}/{len(ids)} profumi...")

    print("\n=== RE-INDICIZZAZIONE COMPLETATA CON SUCCESSO ===")
    print(f"Totale documenti indicizzati: {collection.count()}")


if __name__ == "__main__":
    main()