import json
import re
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = BASE_DIR / "data" / "catalog.json"

class FragranceSearchEngine:
    def __init__(self):
        self.chroma_client = chromadb.Client()

        # Modello multilingue gratuito che gira in locale sul tuo computer
        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-MiniLM-L12-v2"
        )

        self.collection = self.chroma_client.get_or_create_collection(
            name="fragrances",
            embedding_function=self.embed_fn, # type: ignore
            metadata={"hnsw:space": "cosine"}
        )
        self._load_catalog()

    def _load_catalog(self):
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
                "price": float(prod["price"]),
                "in_stock": prod["in_stock"],
                "add_to_cart_url": prod["urls"]["add_to_cart"]
            })

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        print(f"Indicizzati {len(products)} profumi con modello multilingue locale gratuito.")

    def search(
        self,
        query: str,
        min_price: float = None,
        max_price: float = None,
        n_results: int = 5
    ) -> dict:
        """
        Esegue la ricerca ibrida (Semantica + Lessicale su keyword + Filtri di prezzo min/max).
        """
        # Costruzione del filtro nativo 'where' per ChromaDB basato sul prezzo
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

        # 1. Ricerca semantica con supporto al filtro di prezzo nativo (recuperiamo un pool più ampio, es. 8 candidati)
        raw_results = self.collection.query(
            query_texts=[query],
            n_results=min(8, self.collection.count()),
            where=where_clause
        )

        if not raw_results["ids"] or len(raw_results["ids"][0]) == 0:
            return {"ids": [[]], "metadatas": [[]], "documents": [[]], "exact_match_found": False}

        # 2. Identificazione parole chiave rilevanti (note/termini specifici)
        stop_words = {"vorrei", "cerco", "profumo", "fragranza", "con", "nota", "note", "di", "al", "alla", "un", "una", "del", "il", "la", "i", "gli", "le"}
        keywords = [w.lower() for w in re.findall(r"\b[a-zA-Zàèéìòù]+\b", query) if w.lower() not in stop_words and len(w) > 2]

        filtered_ids = []
        filtered_metas = []
        filtered_docs = []

        # 3. Se ci sono parole chiave specifiche, privilegiamo i prodotti che contengono ESPLICITAMENTE quel termine
        if keywords:
            for i, doc in enumerate(raw_results["documents"][0]):
                doc_lower = doc.lower()
                meta = raw_results["metadatas"][0][i]
                # Controllo ulteriore di sicurezza sul prezzo in Python (per coerenza)
                price = meta.get("price", 0.0)
                if min_price is not None and price < min_price:
                    continue
                if max_price is not None and price > max_price:
                    continue

                # Match lessicale: almeno una delle note richieste è presente nel testo?
                if any(kw in doc_lower for kw in keywords):
                    filtered_ids.append(raw_results["ids"][0][i])
                    filtered_metas.append(meta)
                    filtered_docs.append(doc)

        # Se nessun prodotto contiene la parola esatta o non c'erano keyword strette,
        # usiamo i migliori risultati semantici filtrati per prezzo
        if not filtered_ids:
            # Applichiamo comunque il filtro Python sui metadati nel fallback
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
    engine = FragranceSearchEngine()

    test_queries = [
        "profumo con note di vaniglia dolce",
        "brezza marina e salsedine",
        "profumo legnoso elegante per la sera"
    ]

    for q in test_queries:
        print(f"\nDomanda: '{q}'")
        res = engine.search(query=q, n_results=2)
        for i in range(len(res["ids"][0])):
            name = res["metadatas"][0][i]["name"] # type: ignore
            price = res["metadatas"][0][i]["price"] # type: ignore
            print(f"  [{i+1}] {name} - Prezzo: {price}€")