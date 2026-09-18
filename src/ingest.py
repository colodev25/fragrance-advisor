"""
build_catalog.py / ingest.py

Scarica i prodotti della categoria 'profumi' tramite WooCommerce Store API,
arricchisce i dati (Brand, Piramide Olfattiva, Descrizione, Semantic Text),
scarta i prodotti non pertinenti e salva catalog.json per il motore vettoriale.

Uso:
    pip install requests beautifulsoup4
    python src/ingest.py
"""

import html
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------- CONFIG ----------------
SITE = "https://www.trasparenzeprofumeria.it"
BASE = f"{SITE}/wp-json/wc/store/v1"
CATEGORY_SLUG = "profumi"

# Se un prodotto ha ALMENO UNO di questi testi in un tag, viene scartato
#EXCLUDED_TAGS = ["crema corpo", "bagnodoccia", "doccia schiuma", "sapone", "shampoo", "cosmesi"]
EXCLUDED_KEYWORDS = [
    "cosmesi", "skincare", "skin care", "solari", "cura del corpo", 
    "trattamento", "trattamenti", "accessori",
    "crema", "creme", "siero", "serum", "maschera", "scrub", 
    "peeling", "tonico", "lozione", "bagnodoccia", "doccia schiuma", 
    "bagnoschiuma", "sapone", "shampoo", "balsamo", "olio corpo", 
    "deodorante", "emulsione", "contour", "detergente", "struccante",
    "latte corpo", "gel doccia", "candela", "diffusore"
]

# Cartella dello script = root del progetto
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "catalog.json"
DROPPED_FILE = DATA_DIR / "scartati.json"

PER_PAGE = 100
PAUSE = 1.0
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (catalog-builder)"}

# Categorie/slug di sistema da ignorare per l'individuazione del Brand
SYSTEM_CATEGORIES = {
    "profumi", "fragranze", "promozioni", "promozioni-esclusive",
    "outlet", "novita", "in-evidenza", "ultimi-pezzi", "face-out", "campioni","nuovi-eventi", "nuovi eventi"
}
# ----------------------------------------

session = requests.Session()
session.headers.update(HEADERS)


def norm(text: str) -> str:
    """Minuscolo, senza accenti, senza spazi/trattini/punteggiatura."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


#EXCLUDED_NORM = [norm(t) for t in EXCLUDED_TAGS]
EXCLUDED_NORM = [norm(t) for t in EXCLUDED_KEYWORDS]


def clean_html(raw_html: str) -> str:
    """Rimuove tag HTML, decodifica entità e normalizza gli spazi."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_brand(product: dict) -> str:
    """Ricava il Brand del profumo scartando le categorie generiche di WooCommerce."""
    # 1. Controlla prima se WooCommerce espone direttamente la chiave brand/attributes
    if "brands" in product and product["brands"]:
        return product["brands"][0].get("name", "Profumeria Artistica")

    # 2. Isola il brand dalle categorie assegnate al prodotto
    for cat in product.get("categories", []):
        slug = cat.get("slug", "").lower().strip()
        name = cat.get("name", "").strip()

        # Salta categorie di servizio, promozioni o la radice 'profumi'
        if any(term in slug for term in ["promozion", "offerta", "stock", "face-out", "ultimo-pezzo"]):
            continue
        if slug in SYSTEM_CATEGORIES:
            continue

        return name if name else slug.replace("-", " ").title()

    return "Profumeria Artistica"


def parse_olfactory_pyramid(description: str, tags: list) -> dict:
    """Estrae Note di Testa, Cuore e Fondo dalla descrizione; fallback sui tags."""
    pyramid = {
        "top": [],
        "heart": [],
        "base": []
    }

    if not description:
        pyramid["heart"] = tags
        return pyramid

    # Regex per intercettare i formati italiani più frequenti
    top_match = re.search(r"note\s+di\s+testa\s*:\s*([^.\n\r]+)", description, re.IGNORECASE)
    heart_match = re.search(r"note\s+di\s+cuore\s*:\s*([^.\n\r]+)", description, re.IGNORECASE)
    base_match = re.search(r"note\s+di\s+fondo\s*:\s*([^.\n\r]+)", description, re.IGNORECASE)

    def clean_notes(raw: str) -> list:
        parts = re.split(r"[,;–\-/]", raw)
        return [p.strip().capitalize() for p in parts if len(p.strip()) > 1]

    if top_match:
        pyramid["top"] = clean_notes(top_match.group(1))
    if heart_match:
        pyramid["heart"] = clean_notes(heart_match.group(1))
    if base_match:
        pyramid["base"] = clean_notes(base_match.group(1))

    # Se non c'è una piramide esplicita nel testo, usa i tag come accordi generali di cuore
    if not pyramid["top"] and not pyramid["heart"] and not pyramid["base"]:
        pyramid["heart"] = tags

    return pyramid


def build_semantic_text(name: str, brand: str, pyramid: dict, tags: list, description: str) -> str:
    """Genera la stringa ad alta densità semantica per il modello di embedding."""
    tags_str = ", ".join(tags) if tags else "Artistico"
    top_str = ", ".join(pyramid.get("top", [])) or "Note di testa fresche/aromatiche"
    heart_str = ", ".join(pyramid.get("heart", [])) or tags_str
    base_str = ", ".join(pyramid.get("base", [])) or tags_str

    desc_snippet = description[:350].strip() if description else ""

    return (
        f"Profumo {name} di {brand}. "
        f"Famiglie olfattive e sfumature: {tags_str}. "
        f"Note di testa: {top_str}. Note di cuore: {heart_str}. Note di fondo: {base_str}. "
        f"Dettagli ed evoluzione: {desc_snippet}"
    )


def get(url, params=None, retries=3):
    """GET con tentativi progressivi in caso di errori di rete o 5xx."""
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


def is_excluded(product: dict) -> bool:
    """Scarta il prodotto se appartiene a cosmesi o se il nome/tag/categoria contengono termini esclusi."""
    name_norm = norm(product.get("name", ""))
    
    # 1. Controllo sul nome del prodotto (es. 'Crema Viso 50ml')
    if any(bad in name_norm for bad in EXCLUDED_NORM):
        return True

    # 2. Controllo sulle categorie WooCommerce (slug e name)
    for cat in product.get("categories", []):
        cat_slug = norm(cat.get("slug", ""))
        cat_name = norm(cat.get("name", ""))
        if any(bad in cat_slug or bad in cat_name for bad in EXCLUDED_NORM):
            return True

    # 3. Controllo sui tag
    for tag in product.get("tags", []):
        t_name = norm(tag.get("name", ""))
        t_slug = norm(tag.get("slug", ""))
        if any(bad in t_name or bad in t_slug for bad in EXCLUDED_NORM):
            return True

    return False


def slim(product):
    """Arricchisce e normalizza i dati del prodotto per il catalogo semantico."""
    prices = product["prices"]
    minor = prices["currency_minor_unit"]  # es. 2 => "1999" = 19,99
    price = int(prices["price"]) / 10**minor if prices.get("price") else 0.0

    raw_desc = product.get("description", "") or product.get("short_description", "")
    description = clean_html(raw_desc)

    tags = [t["name"] for t in product.get("tags", [])]
    brand = extract_brand(product)
    pyramid = parse_olfactory_pyramid(description, tags)
    semantic_text = build_semantic_text(product["name"], brand, pyramid, tags, description)

    return {
        "id": f"wc_{product['id']}",
        "woocommerce_product_id": product["id"],
        "name": product["name"],
        "brand": brand,
        "sku": product.get("sku", ""),
        "price": price,
        "currency": "EUR",
        "in_stock": product.get("is_in_stock", True),
        "categories": [c["slug"] for c in product.get("categories", [])],
        "tags": tags,
        "olfactory_pyramid": pyramid,
        "description": description,
        "urls": {
            "product_page": product.get("permalink", f"{SITE}/?p={product['id']}"),
            "add_to_cart": f"{SITE}/cart/?add-to-cart={product['id']}",
            "image_url": product["images"][0]["src"] if product.get("images") else None,
        },
        "semantic_text": semantic_text,
    }


def save_json(path, data):
    """Scrittura atomica per garantire l'integrità del catalogo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main():
    cat_id = get_category_id(CATEGORY_SLUG)
    print(f"Categoria '{CATEGORY_SLUG}' -> id {cat_id}")

    raw = list({p["id"]: p for p in fetch_products(cat_id)}.values())
    if not raw:
        raise SystemExit("Nessun prodotto ricevuto: catalogo esistente lasciato intatto.")

    kept = [p for p in raw if not is_excluded(p)]
    dropped = [p for p in raw if is_excluded(p)]

    save_json(OUTPUT_FILE, [slim(p) for p in kept])
    save_json(DROPPED_FILE, [slim(p) for p in dropped])

    print(f"\n{len(raw)} scaricati, {len(kept)} tenuti, {len(dropped)} scartati")
    if dropped:
        print("\nEsempio prodotti scartati:")
        for p in dropped[:3]:
            tags = ", ".join(t["name"] for t in p.get("tags", []))
            print(f"  - {p['name']} (tag: {tags})")

    print(f"\nSalvataggio completato in {OUTPUT_FILE} con brand, piramidi e semantic_text!")


if __name__ == "__main__":
    main()