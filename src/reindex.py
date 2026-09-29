"""
reindex.py - Rigenerazione dell'indice vettoriale ChromaDB tramite motore locale ONNX
"""

import json
import os
import shutil
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "catalog.json"
CHROMA_PATH = BASE_DIR / "chroma_db"
COLLECTION_NAME = "fragrances"


def main():
    print("[*] Avvio re-indicizzazione ChromaDB (Motore Locale ONNX - Zero chiamate API esterne)...")

    if not DATA_PATH.exists():
        print(f"[!] ERRORE: File catalogo non trovato in {DATA_PATH}")
        return

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        products = json.load(f)

    if not products:
        print("[!] ATTENZIONE: Il catalogo è vuoto. Nessun dato da indicizzare.")
        return

    print(f"[*] Caricati {len(products)} prodotti da {DATA_PATH.name}")

    if CHROMA_PATH.exists():
        try:
            shutil.rmtree(CHROMA_PATH)
        except Exception as e:
            print(f"[!] Avviso pulizia chroma_db: {e}")

    CHROMA_PATH.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))

    emb_fn = embedding_functions.DefaultEmbeddingFunction()

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=emb_fn,
        metadata={"hnsw:space": "cosine"}
    )

    documents = []
    metadatas = []
    ids = []

    for item in products:
        doc_id = str(item.get("id"))
        semantic_text = item.get("semantic_text", "")
        if not semantic_text:
            semantic_text = f"{item.get('name', '')} {item.get('brand', '')} {item.get('family', '')} {item.get('description', '')}"

        urls = item.get("urls", {})

        documents.append(semantic_text)
        ids.append(doc_id)
        metadatas.append({
            "name": str(item.get("name", "")),
            "brand": str(item.get("brand", "")),
            "price": float(item.get("price", 0.0)),
            "family": str(item.get("family", "")),
            "ptype": str(item.get("ptype", "")),
            "in_stock": bool(item.get("in_stock", True)),
            "add_to_cart_url": str(urls.get("add_to_cart", "")),
            "product_page_url": str(urls.get("product_page", "")),
            "image_url": str(urls.get("image_url", ""))
        })

    batch_size = 50
    total_docs = len(documents)

    for i in range(0, total_docs, batch_size):
        end_idx = min(i + batch_size, total_docs)
        collection.add(
            documents=documents[i:end_idx],
            metadatas=metadatas[i:end_idx],
            ids=ids[i:end_idx]
        )
        print(f"    Indicizzati {end_idx}/{total_docs} prodotti...")

    print(f"[+] Re-indicizzazione completata con successo in {CHROMA_PATH}\n")


if __name__ == "__main__":
    main()