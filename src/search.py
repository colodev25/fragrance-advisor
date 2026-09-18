import json
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

    def search(self, query: str, max_price: float = None, n_results: int = 2): # type: ignore
        where_filter = {}
        if max_price is not None:
            where_filter = {"price": {"$lte": max_price}}

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter if where_filter else None, # pyright: ignore[reportArgumentType]
            include=["metadatas", "documents", "distances"]
        )
        return results

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