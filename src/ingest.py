"""
build_catalog.py

Scarica i prodotti di una categoria da un negozio WooCommerce (Store API pubblica),
scarta quelli che hanno certi tag indesiderati e salva catalog.json.

Uso:
    pip install requests
    python build_catalog.py
"""

import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests

# ---------------- CONFIG ----------------
SITE = "https://www.trasparenzeprofumeria.it"
BASE = f"{SITE}/wp-json/wc/store/v1"
CATEGORY_SLUG = "profumi"

# Se un prodotto ha ALMENO UNO di questi testi in un tag, viene scartato
EXCLUDED_TAGS = ["crema corpo", "bagnodoccia"]

# Cartella dello script = root del progetto
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "catalog.json"
DROPPED_FILE = DATA_DIR / "scartati.json"  # file di controllo con i prodotti esclusi

PER_PAGE = 100  # massimo consentito dalla Store API
PAUSE = 1.0     # secondi di pausa tra una pagina e l'altra
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (catalog-builder)"}
# ----------------------------------------

session = requests.Session()
session.headers.update(HEADERS)


def norm(text):
    """Minuscolo, senza accenti, senza spazi/trattini/punteggiatura.
    'Bagno Doccia' e 'bagno-doccia' diventano entrambi 'bagnodoccia'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


EXCLUDED_NORM = [norm(t) for t in EXCLUDED_TAGS]


def get(url, params=None, retries=3):
    """GET con qualche tentativo in caso di errori di rete o 5xx."""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == retries:
                raise
            wait = attempt * 2
            print(f"Errore ({e}), riprovo tra {wait}s...")
            time.sleep(wait)


def get_category_id(slug):
    """Ricava l'id numerico della categoria a partire dallo slug."""
    page = 1
    while True:
        r = get(f"{BASE}/products/categories", {"per_page": PER_PAGE, "page": page})
        for cat in r.json():
            if cat["slug"] == slug:
                return cat["id"]
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            raise ValueError(f"Categoria '{slug}' non trovata")
        page += 1


def fetch_products(cat_id):
    """Scarica tutti i prodotti della categoria, pagina per pagina."""
    products, page = [], 1
    while True:
        r = get(
            f"{BASE}/products",
            {"category": cat_id, "per_page": PER_PAGE, "page": page},
        )
        batch = r.json()
        products.extend(batch)
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"Pagina {page}/{total_pages}: {len(batch)} prodotti")
        if page >= total_pages:
            return products
        page += 1
        time.sleep(PAUSE)


def is_excluded(product):
    """True se almeno un tag (nome o slug) contiene una parola da escludere."""
    return any(
        bad in norm(tag["name"]) or bad in norm(tag["slug"])
        for tag in product.get("tags", [])
        for bad in EXCLUDED_NORM
    )


def slim(product):
    """Tiene solo i campi che servono nel catalogo."""
    prices = product["prices"]
    minor = prices["currency_minor_unit"]  # es. 2 => "1999" = 19,99
    return {
        "id": product["id"],
        "name": product["name"],
        "sku": product.get("sku"),
        "price": int(prices["price"]) / 10**minor if prices.get("price") else None,
        "in_stock": product["is_in_stock"],
        "categories": [c["slug"] for c in product["categories"]],
        "tags": [t["name"] for t in product.get("tags", [])],
        "urls": {
            "product_page": product["permalink"],
            "add_to_cart": f"{SITE}/cart/?add-to-cart={product['id']}",
            "image_url": product["images"][0]["src"] if product["images"] else None,
        },
    }


def save_json(path, data):
    """Sovrascrive il file con scrittura atomica: prima su un file temporaneo,
    poi lo sostituisce. Se qualcosa va storto a meta', il file precedente resta intatto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main():
    cat_id = get_category_id(CATEGORY_SLUG)
    print(f"Categoria '{CATEGORY_SLUG}' -> id {cat_id}")

    # dedup per id: se il catalogo cambia durante la paginazione, un prodotto
    # potrebbe comparire due volte
    raw = list({p["id"]: p for p in fetch_products(cat_id)}.values())
    if not raw:
        raise SystemExit("Nessun prodotto ricevuto: catalogo esistente lasciato intatto.")
    kept = [p for p in raw if not is_excluded(p)]
    dropped = [p for p in raw if is_excluded(p)]

    save_json(OUTPUT_FILE, [slim(p) for p in kept])
    save_json(DROPPED_FILE, [slim(p) for p in dropped])

    print(f"\n{len(raw)} scaricati, {len(kept)} tenuti, {len(dropped)} scartati")
    for p in dropped[:5]:
        tags = ", ".join(t["name"] for t in p.get("tags", []))
        print(f"  scartato: {p['name']} (tag: {tags})")
    print(f"\nSalvati {OUTPUT_FILE} e {DROPPED_FILE}")


if __name__ == "__main__":
    main()