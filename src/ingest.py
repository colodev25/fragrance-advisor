"""
build_catalog.py / ingest.py

Scarica i prodotti della categoria 'profumi' tramite WooCommerce Store API,
applica i filtri di esclusione (cosmesi, creme, bagnoschiuma),
arricchisce i dati tramite pipeline ibrida (Regex + LLM Fallback con Groq)
e salva catalog.json e scartati.json per il motore vettoriale.

Uso:
    pip install requests beautifulsoup4 python-dotenv openai
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
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ---------------- CONFIG ----------------
SITE = os.getenv("WC_STORE_URL", "https://www.trasparenzeprofumeria.it").rstrip("/")
BASE = f"{SITE}/wp-json/wc/store/v1"
CATEGORY_SLUG = "profumi"

# Parole chiave per scartare prodotti non pertinenti (cosmesi, corpo, ambiente)
EXCLUDED_KEYWORDS = [
    "cosmesi", "skincare", "skin care", "solari", "cura del corpo", 
    "trattamento", "trattamenti", "accessori",
    "crema", "creme", "siero", "serum", "maschera", "scrub", 
    "peeling", "tonico", "lozione", "bagnodoccia", "doccia schiuma", 
    "bagnoschiuma", "sapone", "shampoo", "balsamo", "olio corpo", 
    "deodorante", "emulsione", "contour", "detergente", "struccante",
    "latte corpo", "gel doccia", "candela", "diffusore", "ambiente"
]

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "catalog.json"
DROPPED_FILE = DATA_DIR / "scartati.json"

PER_PAGE = 100
PAUSE = 1.0
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (catalog-builder)"}

SYSTEM_CATEGORIES = {
    "profumi", "fragranze", "promozioni", "promozioni-esclusive",
    "outlet", "novita", "in-evidenza", "ultimi-pezzi", "face-out", 
    "campioni", "nuovi-eventi", "nuovi eventi"
}

# Client Groq per fallback semantico
GROQ_KEY = os.getenv("GROQ_API_KEY")
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_KEY
) if GROQ_KEY else None
# ----------------------------------------

session = requests.Session()
session.headers.update(HEADERS)


def norm(text: str) -> str:
    """Minuscolo, senza accenti, senza spazi/trattini/punteggiatura."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


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
    """Ricava il Brand del profumo scartando le categorie generiche."""
    if "brands" in product and product["brands"]:
        return html.unescape(product["brands"][0].get("name", "Profumeria Artistica")).strip()

    for cat in product.get("categories", []):
        slug = cat.get("slug", "").lower().strip()
        name = html.unescape(cat.get("name", "")).strip()

        if any(term in slug for term in ["promozion", "offerta", "stock", "face-out", "ultimo-pezzo"]):
            continue
        if slug in SYSTEM_CATEGORIES:
            continue

        return name if name else slug.replace("-", " ").title()

    return "Profumeria Artistica"


def extract_pyramid_regex(description: str) -> dict:
    """
    Fase 1: Tenta di individuare le note olfattive tramite pattern classici
    supportando formati italiani ed inglesi.
    """
    pyramid = {"top": [], "heart": [], "base": []}
    if not description:
        return pyramid

    patterns = {
        "top": r"(?:note\s+di\s+testa|testa|top\s+notes?)\s*[:\-]\s*([^.\n\r]+?)(?=(?:note\s+di|testa|cuore|fondo|top|heart|base|\.|\n|\r|$))",
        "heart": r"(?:note\s+di\s+cuore|cuore|heart\s+notes?|middle\s+notes?)\s*[:\-]\s*([^.\n\r]+?)(?=(?:note\s+di|testa|cuore|fondo|top|heart|base|\.|\n|\r|$))",
        "base": r"(?:note\s+di\s+fondo|fondo|base\s+notes?)\s*[:\-]\s*([^.\n\r]+?)(?=(?:note\s+di|testa|cuore|fondo|top|heart|base|\.|\n|\r|$))",
    }

    found = False
    for section, pattern in patterns.items():
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            raw_items = match.group(1)
            parts = re.split(r"[,;–\-/•]", raw_items)
            cleaned = [p.strip().capitalize() for p in parts if len(p.strip()) > 1 and not p.strip().isdigit()]
            if cleaned:
                pyramid[section] = cleaned
                found = True

    return pyramid if found else {"top": [], "heart": [], "base": []}


def extract_pyramid_llm(name: str, brand: str, description: str) -> dict:
    """
    Fase 2: Fallback semantico con Groq gpt-oss-20b per descrizioni narrative o discorsive.
    """
    empty = {"top": [], "heart": [], "base": []}
    if not client or not description or len(description.strip()) < 30:
        return empty

    desc_sample = description if len(description) <= 1500 else (description[:700] + "\n...\n" + description[-800:])

    prompt = (
        f"Profumo: '{name}' di '{brand}'.\n"
        f"Testo descrittivo:\n\"\"\"{desc_sample}\"\"\"\n\n"
        "COMPITO:\n"
        "Estrai gli ingredienti olfattivi (agrumi, frutti, fiori, spezie, legni, resine, muschi, accordi) "
        "e suddividili nella piramide olfattiva (top, heart, base).\n\n"
        "REGOLE TASSATIVE:\n"
        "1. Includi solo ingredienti reali (es. lime, arancia dolce, ylang ylang, sandalo, ambra grigia).\n"
        "2. NON inserire aggettivi astratti o marketing (es. 'femminilità', 'sfrenate', 'passione', 'peccato').\n"
        "3. Se nel testo le note sono elencate alla fine senza etichetta (es. 'Lime, arancia...', 'Passion fruit, pesca...', 'Ambra, sandalo...'), "
        "assegnale nell'ordine logico a top, heart e base.\n"
        "4. Rispondi ESCLUSIVAMENTE con un JSON valido in questo formato esatto:\n"
        "{\n"
        "  \"top\": [\"nota1\", \"nota2\"],\n"
        "  \"heart\": [\"nota3\", \"nota4\"],\n"
        "  \"base\": [\"nota5\", \"nota6\"]\n"
        "}"
    )

    for attempt in range(3):
        try:
            res = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=250
            )
            content = res.choices[0].message.content.strip()
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                return {
                    "top": [str(x).strip().capitalize() for x in data.get("top", []) if len(str(x).strip()) > 1],
                    "heart": [str(x).strip().capitalize() for x in data.get("heart", []) if len(str(x).strip()) > 1],
                    "base": [str(x).strip().capitalize() for x in data.get("base", []) if len(str(x).strip()) > 1]
                }
            return empty
        except Exception as e:
            if "429" in str(e):
                time.sleep(2 * (attempt + 1))
            else:
                break
    return empty


def parse_olfactory_pyramid_hybrid(description: str, tags: list, name: str, brand: str, use_llm: bool = True) -> tuple[dict, str]:
    """
    Pipeline ibrida per l'estrazione delle note:
    1. Prova prima con regex veloci.
    2. Se mancano note e use_llm=True, invoca Groq LLM.
    3. Fallback sui tags in caso di insuccesso totale.
    """
    pyramid = extract_pyramid_regex(description)
    total_notes = len(pyramid["top"]) + len(pyramid["heart"]) + len(pyramid["base"])

    if total_notes >= 3:
        return pyramid, "regex"

    if use_llm and client and len(description) > 30:
        llm_pyramid = extract_pyramid_llm(name, brand, description)
        llm_notes_count = len(llm_pyramid["top"]) + len(llm_pyramid["heart"]) + len(llm_pyramid["base"])
        if llm_notes_count > 0:
            # Piccola pausa funzionale per evitare rate-limit con Groq
            time.sleep(0.2)
            return llm_pyramid, "llm"

    # Fallback sui tag
    if not pyramid["top"] and not pyramid["heart"] and not pyramid["base"]:
        pyramid["heart"] = [t.capitalize() for t in tags]

    return pyramid, "tags"


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
        print(f"Pagina {page}/{total_pages}: {len(batch)} prodotti scaricati...")
        if page >= total_pages:
            return products
        page += 1
        time.sleep(PAUSE)


def is_excluded(product: dict) -> bool:
    """Scarta il prodotto se appartiene a cosmesi o se il nome/tag/categoria contengono termini esclusi."""
    name_norm = norm(product.get("name", ""))
    
    if any(bad in name_norm for bad in EXCLUDED_NORM):
        return True

    for cat in product.get("categories", []):
        cat_slug = norm(cat.get("slug", ""))
        cat_name = norm(cat.get("name", ""))
        if any(bad in cat_slug or bad in cat_name for bad in EXCLUDED_NORM):
            return True

    for tag in product.get("tags", []):
        t_name = norm(tag.get("name", ""))
        t_slug = norm(tag.get("slug", ""))
        if any(bad in t_name or bad in t_slug for bad in EXCLUDED_NORM):
            return True

    return False


def slim(product: dict, use_llm: bool = True) -> tuple[dict, str]:
    """Arricchisce e normalizza i dati del prodotto per il catalogo semantico."""
    prices = product.get("prices", {})
    minor = prices.get("currency_minor_unit", 2)
    price = int(prices["price"]) / 10**minor if prices.get("price") else 0.0

    raw_desc = product.get("description", "") or product.get("short_description", "")
    description = clean_html(raw_desc)

    clean_name = html.unescape(product.get("name", "")).strip()
    tags = [t["name"] for t in product.get("tags", [])]
    brand = extract_brand(product)

    pyramid, source = parse_olfactory_pyramid_hybrid(
        description, tags, name=clean_name, brand=brand, use_llm=use_llm
    )
    semantic_text = build_semantic_text(clean_name, brand, pyramid, tags, description)

    entry = {
        "id": f"wc_{product['id']}",
        "woocommerce_product_id": product["id"],
        "name": clean_name,
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
    return entry, source


def save_json(path, data):
    """Scrittura atomica per garantire l'integrità del catalogo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main():
    print("=== AVVIO PIPELINE DI INGESTIONE CATALOGO ===")
    cat_id = get_category_id(CATEGORY_SLUG)
    print(f"Categoria '{CATEGORY_SLUG}' identificata con id: {cat_id}")

    raw_products = fetch_products(cat_id)
    raw = list({p["id"]: p for p in raw_products}.values())
    if not raw:
        raise SystemExit("Nessun prodotto ricevuto: catalogo esistente lasciato intatto.")

    kept = [p for p in raw if not is_excluded(p)]
    dropped = [p for p in raw if is_excluded(p)]

    print(f"\nScaricati: {len(raw)} | Selezionati (Profumi): {len(kept)} | Esclusi: {len(dropped)}")

    print(f"\n[*] Elaborazione e arricchimento olfattivo di {len(kept)} profumi...")
    kept_processed = []
    regex_count = 0
    llm_count = 0
    tags_count = 0

    for i, p in enumerate(kept, 1):
        item, source = slim(p, use_llm=True)
        kept_processed.append(item)

        if source == "regex":
            regex_count += 1
        elif source == "llm":
            llm_count += 1
        else:
            tags_count += 1

        if i % 25 == 0 or i == len(kept):
            print(f"    Elaborati {i}/{len(kept)} profumi...")

    # I prodotti scartati vengono processati senza sprecare token LLM
    dropped_processed = [slim(p, use_llm=False)[0] for p in dropped]

    save_json(OUTPUT_FILE, kept_processed)
    save_json(DROPPED_FILE, dropped_processed)

    print("\n=== RIEPILOGO GENERAZIONE CATALOGO ===")
    print(f"Salvati in {OUTPUT_FILE}: {len(kept_processed)} profumi")
    print(f"  - Note estratte via Regex diretta:       {regex_count}")
    print(f"  - Note recuperate con Groq LLM:          {llm_count}")
    print(f"  - Fallback sui tag (nessuna nota nel testo): {tags_count}")
    print(f"Salvati in {DROPPED_FILE}: {len(dropped_processed)} articoli esclusi")


if __name__ == "__main__":
    main()