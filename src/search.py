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


    def search(self, query: str, max_price: float = None, n_results: int = 3):
        # 1. Ricerca semantica standard (recuperiamo un pool più ampio, es. 8 candidati)
        raw_results = self.collection.query(
            query_texts=[query],
            n_results=min(8, self.collection.count())
        )

        if not raw_results["ids"] or len(raw_results["ids"][0]) == 0:
            return {"ids": [[]], "metadatas": [[]], "documents": [[]]}

        # 2. Identificazione parole chiave rilevanti (note/termini specifici)
        # Escludiamo stop words comuni
        stop_words = {"vorrei", "cerco", "profumo", "fragranza", "con", "nota", "note", "di", "al", "alla", "un", "una", "del"}
        keywords = [w.lower() for w in re.findall(r"\b[a-zA-Zàèéìòù]+\b", query) if w.lower() not in stop_words and len(w) > 2]

        filtered_ids = []
        filtered_metas = []
        filtered_docs = []

        # 3. Se ci sono parole chiave specifiche (es. "fico", "caramello", "rosa"),
        # privilegiamo i prodotti che contengono ESPLICITAMENTE quel termine nel documento
        if keywords:
            for i, doc in enumerate(raw_results["documents"][0]):
                doc_lower = doc.lower()
                # Match lessicale: almeno una delle note richieste è presente nel testo?
                if any(kw in doc_lower for kw in keywords):
                    filtered_ids.append(raw_results["ids"][0][i])
                    filtered_metas.append(raw_results["metadatas"][0][i])
                    filtered_docs.append(doc)

        # Se nessun prodotto contiene la parola esatta o non c'erano keyword strette,
        # usiamo i migliori risultati semantici di fallback
        if not filtered_ids:
            return {
                "ids": [raw_results["ids"][0][:n_results]],
                "metadatas": [raw_results["metadatas"][0][:n_results]],
                "documents": [raw_results["documents"][0][:n_results]],
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
            name = res["metadatas"][0][i]["name"] # pyright: ignore[reportOptionalSubscript]
            dist = res["distances"][0][i] # pyright: ignore[reportOptionalSubscript]
            print(f"  [{i+1}] {name} - Distanza: {dist:.3f}")