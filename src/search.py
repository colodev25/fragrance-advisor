"""
search.py - Motore di Ricerca Semantico e Ibrido

Indicizza data/catalog.json su ChromaDB in locale tramite SentenceTransformers,
applica filtri di budget (min_price, max_price) e reranking lessicale su note olfattive.

Uso per test:
    python src/search.py
"""

import json
import re
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = BASE_DIR / "data" / "catalog.json"


class FragranceSearchEngine:
    def __init__(self):
        # Client ChromaDB in-memory (veloce, si popola ad ogni avvio da catalog.json)
        self.chroma_client = chromadb.Client()

        # Modello multilingue leggero e ad alte prestazioni locale
        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-MiniLM-L12-v2"
        )

        self.collection = self.chroma_client.get_or_create_collection(
            name="fragrances",
            embedding_function=self.embed_fn,  # type: ignore
            metadata={"hnsw:space": "cosine"}
        )
        self._load_catalog()

    def _load_catalog(self):
        if not CATALOG_PATH.exists():
            print(f"[!] File non trovato: {CATALOG_PATH}. Esegui prima 'python src/ingest.py'.")
            return

        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            products = json.load(f)

        ids = []
        documents = []
        metadatas = []

        for prod in products:
            ids.append(prod["id"])
            documents.append(prod["semantic_text"])
            metadatas.append({
                "name": prod["name"],
                "brand": prod["brand"],
                "price": float(prod.get("price", 0.0)),
                "in_stock": bool(prod.get("in_stock", True)),
                "family": prod.get("family", ""),
                "ptype": prod.get("ptype", ""),
                "add_to_cart_url": prod["urls"].get("add_to_cart", ""),
                "product_page_url": prod["urls"].get("product_page", ""),
                "image_url": prod["urls"].get("image_url", "")
            })

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        print(f"[*] Indicizzati {len(products)} profumi Shopify in ChromaDB con modello multilingue.")

    def search(
        self,
        query: str,
        min_price: float = None,
        max_price: float = None,
        n_results: int = 5
    ) -> dict:
        """
        Esegue la ricerca ibrida:
        1. Query vettoriale semantica con filtri where di prezzo su ChromaDB.
        2. Reranking lessicale se la query menziona note olfattive specifiche.
        """
        where_clause = None
        conditions = []

        if min_price is not None:
            conditions.append({"price": {"$gte": float(min_price)}})
        if max_price is not None:
            conditions.append({"price": {"$lte": float(max_price)}})

        if len(conditions) == 1:
            where_clause = conditions[0]
        elif len(conditions) > 1:
            where_clause = {"$and": conditions}

        # 1. Recupero semantico iniziale
        total_items = self.collection.count()
        if total_items == 0:
            return {"ids": [[]], "metadatas": [[]], "documents": [[]], "exact_match_found": False}

        raw_results = self.collection.query(
            query_texts=[query],
            n_results=min(10, total_items),
            where=where_clause
        )

        if not raw_results["ids"] or len(raw_results["ids"][0]) == 0:
            return {"ids": [[]], "metadatas": [[]], "documents": [[]], "exact_match_found": False}

        # 2. Reranking lessicale su note e parole chiave
        stop_words = {
            "vorrei", "cerco", "profumo", "fragranza", "con", "nota", "note", 
            "di", "al", "alla", "un", "una", "del", "il", "la", "i", "gli", "le", "per"
        }
        keywords = [
            w.lower() for w in re.findall(r"\b[a-zA-Zàèéìòù]+\b", query) 
            if w.lower() not in stop_words and len(w) > 2
        ]

        filtered_ids = []
        filtered_metas = []
        filtered_docs = []

        if keywords:
            for i, doc in enumerate(raw_results["documents"][0]):
                doc_lower = doc.lower()
                meta = raw_results["metadatas"][0][i]
                price = meta.get("price", 0.0)

                # Controllo di sicurezza sul prezzo
                if min_price is not None and price < min_price:
                    continue
                if max_price is not None and price > max_price:
                    continue

                if any(kw in doc_lower for kw in keywords):
                    filtered_ids.append(raw_results["ids"][0][i])
                    filtered_metas.append(meta)
                    filtered_docs.append(doc)

        # Fallback se non ci sono keyword strette o match lessicale
        if not filtered_ids:
            valid_ids = []
            valid_metas = []
            valid_docs = []

            for i, doc in enumerate(raw_results["documents"][0]):
                meta = raw_results["metadatas"][0][i]
                price = meta.get("price", 0.0)
                if min_price is not None and price < min_price:
                    continue
                if max_price is not None and price > max_price:
                    continue
                valid_ids.append(raw_results["ids"][0][i])
                valid_metas.append(meta)
                valid_docs.append(doc)

            return {
                "ids": [valid_ids[:n_results]],
                "metadatas": [valid_metas[:n_results]],
                "documents": [valid_docs[:n_results]],
                "exact_match_found": False
            }

        return {
            "ids": [filtered_ids[:n_results]],
            "metadatas": [filtered_metas[:n_results]],
            "documents": [filtered_docs[:n_results]],
            "exact_match_found": True
        }


if __name__ == "__main__":
    print("=== TEST RICERCA CHROMADB (SHOPIFY) ===")
    engine = FragranceSearchEngine()

    test_queries = [
        ("profumo marino con alghe ed estate", None, None),
        ("fragranza all'iris elegante e raffinata", None, None),
        ("profumo da sera economico", None, 150.0),
        ("alta gamma oltre 200 euro", 200.0, None)
    ]

    for q, min_p, max_p in test_queries:
        filtro_str = f" [Prezzo: min={min_p}, max={max_p}]" if (min_p or max_p) else ""
        print(f"\n🔍 Query: '{q}'{filtro_str}")
        res = engine.search(query=q, min_price=min_p, max_price=max_p, n_results=2)

        if res["ids"] and len(res["ids"][0]) > 0:
            for i in range(len(res["ids"][0])):
                m = res["metadatas"][0][i]
                print(f"   [{i+1}] {m['name']} ({m['brand']}) - Prezzo: {m['price']}€ | Famiglia: {m.get('family', 'N/D')}")
                print(f"       Cart URL: {m['add_to_cart_url']}")
        else:
            print("   Nessun risultato trovato con questi filtri.")