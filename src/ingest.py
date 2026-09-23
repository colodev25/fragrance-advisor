"""
ingest.py - Shopify Universal Extractor (Sanitized Edition)

Scarica il catalogo tramite /products.json di Shopify, analizza i blocchi
collapsible dinamici del tema (Piramide, Famiglia, Tipologia, Usage Profile),
elimina tassativamente tag HTML (<br>), tronca metadati estranei (formato, EDP)
e produce data/catalog.json strutturato per ChromaDB e l'Advisor.

Uso:
    python src/ingest.py
"""

import html
import json
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ---------------- CONFIGURAZIONE ----------------
SITE = os.getenv("SHOPIFY_STORE_URL", "").rstrip("/")
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "catalog.json"
DROPPED_FILE = DATA_DIR / "scartati.json"

PER_PAGE = 250
TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (Shopify-Catalog-Ingest)"}

ALLOWED_TYPES = {"fragranze", "profumi", "profumo", "eau de parfum", "extrait de parfum"}

EXCLUDED_KEYWORDS = [
    "crema", "bagnodoccia", "doccia schiuma", "sapone", "shampoo",
    "balsamo", "olio corpo", "candela", "diffusore", "ambiente",
    "solare", "siero", "scrub", "lozione", "deodorante"
]

GROQ_KEY = os.getenv("GROQ_API_KEY")
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_KEY
) if GROQ_KEY else None

session = requests.Session()
session.headers.update(HEADERS)
# ------------------------------------------------


def clean_text(raw_text: str) -> str:
    """Rimuove tassativamente tag HTML, entità speciali e spazi multipli."""
    if not raw_text:
        return ""
    text = re.sub(r"<\s*br\s*/?>", " ", raw_text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"&[a-zA-Z0-9#]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_note_items(raw_text: str) -> list[str]:
    """
    Sanitizza le note olfattive:
    1. Rimuove qualsiasi tag HTML residuo (<br>, <span>, ecc.) ed entità.
    2. Tronca immediatamente metadati spuri (Formato:, EDP, ml, ecc.).
    3. Suddivide su virgole, punti e virgola, trattini e congiunzioni (' e ', ' ed ', ' & ').
    4. Restituisce una lista di ingredienti puliti con iniziale maiuscola.
    """
    if not raw_text:
        return []

    # 1. Sostituisce tag di interruzione con separatori ed elimina tutto l'HTML
    text = re.sub(r"<\s*br\s*/?>", ", ", raw_text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"&[a-zA-Z0-9#]+;", " ", text)

    # 2. Taglia via tutto ciò che segue etichette di metadati (es. 'Formato:', 'Concentrazione:', ecc.)
    text = re.split(
        r"\b(?:formato|formati|concentrazione|tipologia|famiglia|genere|volume|quantit[aà]|confezione|packaging|made\s+in)\s*[:\-]",
        text,
        flags=re.I
    )[0]

    # 3. Rimuove indicazioni di formato residue rimaste isolate (es. 'EDP 2 x 15 ml', '100 ml')
    text = re.sub(r"\b\d+\s*(?:x\s*\d+\s*)?(?:ml|cl|g|gr|oz)\b", "", text, flags=re.I)
    text = re.sub(r"\b(?:edp|edt|extrait\s+de\s+parfum|eau\s+de\s+parfum|eau\s+de\s+toilette)\b", "", text, flags=re.I)

    # 4. Suddivide su punteggiatura e sulle congiunzioni italiane/inglesi ('e', 'ed', '&', 'and')
    raw_parts = re.split(r"[,;–•/\n\r]|\b(?:e|ed|and|&)\b", text, flags=re.I)

    cleaned_list = []
    for part in raw_parts:
        p = re.sub(r"[\.()\*•–\-\"\':]", " ", part).strip()
        p = re.sub(r"\s+", " ", p)

        if not p or len(p) < 2:
            continue
        if p.isdigit():
            continue
        if p.lower() in ["formato", "edp", "edt", "unisex", "donna", "uomo", "parfum"]:
            continue

        if p.isupper():
            p = p.title()
        else:
            p = p[:1].upper() + p[1:]

        cleaned_list.append(p)

    return cleaned_list


def parse_pyramid_from_html(container) -> dict:
    """Estrae le note olfattive convertendo i blocchi HTML in righe separate."""
    pyramid = {"top": [], "heart": [], "base": []}
    if not container:
        return pyramid

    container_copy = BeautifulSoup(str(container), "html.parser")

    # Sostituisce i tag <br> con newline reali per isolare le righe
    for br in container_copy.find_all("br"):
        br.replace_with("\n")

    for block in container_copy.find_all(["p", "div", "li"]):
        block.insert_after("\n")

    raw_lines = container_copy.get_text().split("\n")

    for raw_line in raw_lines:
        line = clean_text(raw_line)
        if not line or len(line) < 3:
            continue

        # Note di Testa
        if re.search(r"\b(?:note\s+di\s+testa|testa|top\s+notes?)\b", line, re.I):
            val = re.split(r"(?:note\s+di\s+testa|testa|top\s+notes?)\s*[:\-]\s*", line, flags=re.I)[-1]
            val = re.split(r"\b(?:note\s+di\s+cuore|note\s+di\s+fondo|cuore|fondo|heart|base|formato\b|formati\b)", val, flags=re.I)[0]
            pyramid["top"].extend(clean_note_items(val))

        # Note di Cuore
        elif re.search(r"\b(?:note\s+di\s+cuore|cuore|heart\s+notes?|middle\s+notes?)\b", line, re.I):
            val = re.split(r"(?:note\s+di\s+cuore|cuore|heart\s+notes?|middle\s+notes?)\s*[:\-]\s*", line, flags=re.I)[-1]
            val = re.split(r"\b(?:note\s+di\s+testa|note\s+di\s+fondo|testa|fondo|top|base|formato\b|formati\b)", val, flags=re.I)[0]
            pyramid["heart"].extend(clean_note_items(val))

        # Note di Fondo
        elif re.search(r"\b(?:note\s+di\s+fondo|fondo|base\s+notes?)\b", line, re.I):
            val = re.split(r"(?:note\s+di\s+fondo|fondo|base\s+notes?)\s*[:\-]\s*", line, flags=re.I)[-1]
            val = re.split(r"\b(?:note\s+di\s+testa|note\s+di\s+cuore|testa|cuore|top|heart|formato\b|formati\b)", val, flags=re.I)[0]
            pyramid["base"].extend(clean_note_items(val))

    for section in pyramid:
        pyramid[section] = list(dict.fromkeys(pyramid[section]))

    return pyramid


def parse_shopify_sections(body_html: str) -> dict:
    """Mappa i collapsibles del tema isolando sezioni tecniche e storytelling."""
    data = {
        "top": [],
        "heart": [],
        "base": [],
        "family": "",
        "ptype": "",
        "usage_profile": "",
        "description": ""
    }

    if not body_html:
        return data

    soup = BeautifulSoup(body_html, "html.parser")
    buttons = soup.find_all("button", class_=lambda c: c and "collapsible-trigger" in c)

    for btn in buttons:
        target_id = btn.get("aria-controls", "").strip()
        btn_title = clean_text(btn.get_text()).lower()

        content_div = None
        if target_id:
            content_div = soup.find(id=re.compile(f"^{re.escape(target_id)}$", re.I))

        if not content_div:
            parent = btn.find_parent(class_=lambda c: c and "collapsibles-wrapper" in c)
            if parent:
                content_div = parent.find(class_=lambda c: c and "collapsible-content" in c)

        if not content_div:
            continue

        inner = content_div.find(class_=lambda c: c and "collapsible-content__inner" in c) or content_div

        # 1. Piramide Olfattiva
        if "piramid" in btn_title or "pyramid" in btn_title or target_id.lower() in ["piramide", "piramideolfattiva"]:
            pyr = parse_pyramid_from_html(inner)
            data["top"] = pyr["top"]
            data["heart"] = pyr["heart"]
            data["base"] = pyr["base"]

        # 2. Famiglia Olfattiva
        elif "famigli" in btn_title or "family" in btn_title or target_id.lower() in ["famiglia", "famigliaolfattiva"]:
            raw_fam = clean_text(inner.get_text())
            data["family"] = re.sub(r"^famiglia\s*(?:olfattiva)?\s*[:\-]\s*", "", raw_fam, flags=re.I).strip()

        # 3. Tipologia di Profumo (ptype)
        elif "tipolog" in btn_title or "concentrazion" in btn_title or target_id.lower() in ["tipologia", "tipologia-profumo"]:
            raw_ptype = clean_text(inner.get_text())
            data["ptype"] = re.sub(r"^tipologia\s*(?:di\s*profumo)?\s*[:\-]\s*", "", raw_ptype, flags=re.I).strip()

        # 4. Usage Profile (Per chi è adatto e quando indossarlo)
        elif any(k in btn_title for k in ["per chi", "quando indossar", "adatto"]) or target_id.lower() in ["why", "perchi"]:
            raw_usage = clean_text(inner.get_text())
            data["usage_profile"] = re.sub(r"^(?:per chi|quando indossarlo)\s*[:\-]\s*", "", raw_usage, flags=re.I).strip()

    # Estrazione testo introduttivo rimuovendo i collapsibles
    soup_intro = BeautifulSoup(body_html, "html.parser")
    for elem in soup_intro.find_all(class_=lambda c: c and ("collapsibles-wrapper" in c or "collapsible-content" in c or "collapsible-trigger" in c)):
        elem.decompose()

    intro_text = clean_text(soup_intro.get_text())
    intro_text = re.sub(r"\bformato\s*:\s*[^\.\n]+", "", intro_text, flags=re.I).strip()
    data["description"] = intro_text

    return data


def extract_pyramid_regex_fallback(text: str) -> dict:
    """Fallback Regex globale per schede prive di accordion standard."""
    pyramid = {"top": [], "heart": [], "base": []}
    if not text:
        return pyramid

    patterns = {
        "top": r"(?:note\s+di\s+testa|testa|top\s+notes?)\s*[:\-]\s*([^.\n\r]+?)(?=(?:note\s+di|testa|cuore|fondo|top|heart|base|\.|\n|\r|$))",
        "heart": r"(?:note\s+di\s+cuore|cuore|heart\s+notes?|middle\s+notes?)\s*[:\-]\s*([^.\n\r]+?)(?=(?:note\s+di|testa|cuore|fondo|top|heart|base|\.|\n|\r|$))",
        "base": r"(?:note\s+di\s+fondo|fondo|base\s+notes?)\s*[:\-]\s*([^.\n\r]+?)(?=(?:note\s+di|testa|cuore|fondo|top|heart|base|\.|\n|\r|$))",
    }

    for section, pattern in patterns.items():
        m = re.search(pattern, text, re.I)
        if m:
            pyramid[section] = clean_note_items(m.group(1))

    return pyramid


def extract_pyramid_llm_fallback(name: str, brand: str, text: str) -> dict:
    """Fallback tramite Groq per schede puramente discorsive."""
    empty = {"top": [], "heart": [], "base": []}
    if not client or not text or len(text.strip()) < 30:
        return empty

    prompt = (
        f"Profumo: '{name}' di '{brand}'.\n"
        f"Testo: \"\"\"{text[:1100]}\"\"\"\n\n"
        "Estrai la piramide olfattiva in JSON escludendo formati, ml e parole di marketing:\n"
        "{\"top\": [\"nota1\"], \"heart\": [\"nota2\"], \"base\": [\"nota3\"]}\n"
        "Rispondi ESCLUSIVAMENTE con il JSON."
    )

    try:
        res = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=220
        )
        m = re.search(r"\{.*\}", res.choices[0].message.content, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            return {
                "top": [n for x in data.get("top", []) for n in clean_note_items(str(x))],
                "heart": [n for x in data.get("heart", []) for n in clean_note_items(str(x))],
                "base": [n for x in data.get("base", []) for n in clean_note_items(str(x))]
            }
    except Exception:
        pass
    return empty


def fetch_all_shopify_products() -> list:
    """Scarica i prodotti dallo store Shopify gestendo la paginazione."""
    if not SITE:
        print("[!] SHOPIFY_STORE_URL non configurato nel file .env.")
        return []

    products = []
    page = 1
    print(f"[*] Connessione a Shopify Store: {SITE}...")

    while True:
        url = f"{SITE}/products.json"
        params = {"limit": PER_PAGE, "page": page}

        try:
            res = session.get(url, params=params, timeout=TIMEOUT)
            if res.status_code != 200:
                print(f"[!] Risposta HTTP {res.status_code} alla pagina {page}: {res.text[:150]}")
                break

            payload = res.json()
            batch = payload.get("products", [])
            if not batch:
                break

            products.extend(batch)
            print(f"    Pagina {page}: scaricati {len(batch)} prodotti (Totale scaricato: {len(products)})...")

            if len(batch) < PER_PAGE:
                break

            page += 1
            time.sleep(0.3)

        except Exception as e:
            print(f"[!] Errore di rete alla pagina {page}: {e}")
            break

    return products


def is_fragrance(prod: dict) -> bool:
    """Esclude cosmesi, accessori, candele o articoli non profumo."""
    p_type = prod.get("product_type", "").strip().lower()
    title = prod.get("title", "").lower()
    tags = [t.lower() for t in prod.get("tags", [])]

    all_str = f"{title} {' '.join(tags)} {p_type}"
    if any(bad in all_str for bad in EXCLUDED_KEYWORDS):
        return False

    if p_type in ALLOWED_TYPES or any(k in all_str for k in ["eau de parfum", "extrait", "millésime", "profumo", "parfum"]):
        return True

    return True if not p_type else False


def transform_product(prod: dict) -> dict:
    """Mappa il prodotto Shopify nello schema catalog.json arricchito e pulito."""
    prod_id = f"sh_{prod['id']}"
    title = clean_text(prod.get("title", ""))
    brand = clean_text(prod.get("vendor", "Profumeria Artistica"))
    handle = prod.get("handle", "")

    variants = prod.get("variants", [])
    available_variants = [v for v in variants if v.get("available", True)]
    active_variants = available_variants if available_variants else variants

    first_var = active_variants[0] if active_variants else {}
    variant_id = first_var.get("id", "")
    sku = first_var.get("sku", "")

    try:
        price = round(float(first_var.get("price", 0.0)), 2)
    except (ValueError, TypeError):
        price = 0.0

    in_stock = any(v.get("available", False) for v in variants) if variants else True

    # 1. Parsing delle sezioni HTML strutturate del tema
    parsed = parse_shopify_sections(prod.get("body_html", ""))

    pyramid = {
        "top": parsed["top"],
        "heart": parsed["heart"],
        "base": parsed["base"]
    }

    # 2. Fallback su tutta la scheda se la piramide è vuota
    total_notes = len(pyramid["top"]) + len(pyramid["heart"]) + len(pyramid["base"])
    if total_notes == 0:
        raw_clean_all = clean_text(prod.get("body_html", ""))
        pyramid = extract_pyramid_regex_fallback(raw_clean_all)
        total_notes = len(pyramid["top"]) + len(pyramid["heart"]) + len(pyramid["base"])

    # 3. Fallback con Groq LLM
    if total_notes == 0:
        desc_sample = parsed["description"] or parsed["usage_profile"] or clean_text(prod.get("body_html", ""))
        pyramid = extract_pyramid_llm_fallback(title, brand, desc_sample)

    ptype = parsed["ptype"]
    if not ptype:
        tags_lower = [t.lower() for t in prod.get("tags", [])]
        if "eau de parfum" in tags_lower:
            ptype = "Eau de Parfum"
        elif "extrait de parfum" in tags_lower:
            ptype = "Extrait de Parfum"

    image_url = ""
    if prod.get("images"):
        image_url = prod["images"][0].get("src", "")
    elif first_var.get("featured_image"):
        image_url = first_var["featured_image"].get("src", "")

    urls = {
        "product_page": f"{SITE}/products/{handle}" if handle else "",
        "add_to_cart": f"{SITE}/cart/{variant_id}:1" if variant_id else "",
        "image_url": image_url
    }

    tags_list = prod.get("tags", [])
    tags_str = ", ".join(tags_list) if tags_list else "Artistico"
    top_str = ", ".join(pyramid["top"]) if pyramid["top"] else "fresche/agrumate"
    heart_str = ", ".join(pyramid["heart"]) if pyramid["heart"] else "floreali/speziate"
    base_str = ", ".join(pyramid["base"]) if pyramid["base"] else "legnose/ambrate"
    family_str = parsed["family"] or "Profumeria Artistica"
    ptype_str = ptype or "Eau de Parfum"
    context_str = parsed["usage_profile"][:300] if parsed["usage_profile"] else parsed["description"][:300]

    semantic_text = (
        f"Profumo {title} di {brand}. "
        f"Tipologia: {ptype_str}. "
        f"Famiglia olfattiva: {family_str}. Tag: {tags_str}. "
        f"Note di testa: {top_str}. Note di cuore: {heart_str}. Note di fondo: {base_str}. "
        f"Carattere, contesto d'uso e occasioni: {context_str}"
    )

    return {
        "id": prod_id,
        "shopify_product_id": prod["id"],
        "name": title,
        "brand": brand,
        "sku": sku,
        "price": price,
        "currency": "EUR",
        "in_stock": in_stock,
        "tags": tags_list,
        "olfactory_pyramid": pyramid,
        "family": parsed["family"],
        "ptype": ptype,
        "usage_profile": parsed["usage_profile"],
        "description": parsed["description"],
        "urls": urls,
        "semantic_text": semantic_text
    }


def main():
    print("=== AVVIO PIPELINE DI INGESTIONE SHOPIFY (SANITIZED) ===")
    raw_products = fetch_all_shopify_products()
    if not raw_products:
        print("[!] Nessun prodotto recuperato. Verifica SHOPIFY_STORE_URL nel file .env.")
        return

    kept_products = [p for p in raw_products if is_fragrance(p)]
    dropped_products = [p for p in raw_products if not is_fragrance(p)]

    print(f"\nScaricati: {len(raw_products)} | Riconosciuti come Profumi: {len(kept_products)} | Esclusi: {len(dropped_products)}")

    print(f"[*] Elaborazione semantica e sanitizzazione di {len(kept_products)} profumi...")
    catalog = []
    pyramids_found = 0
    families_found = 0
    ptypes_found = 0
    usage_found = 0

    for i, p in enumerate(kept_products, 1):
        item = transform_product(p)
        catalog.append(item)

        total_notes = len(item["olfactory_pyramid"]["top"]) + len(item["olfactory_pyramid"]["heart"]) + len(item["olfactory_pyramid"]["base"])
        if total_notes > 0:
            pyramids_found += 1
        if item["family"]:
            families_found += 1
        if item["ptype"]:
            ptypes_found += 1
        if item["usage_profile"]:
            usage_found += 1

        if i % 50 == 0 or i == len(kept_products):
            print(f"    Elaborati {i}/{len(kept_products)} profumi...")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    with open(DROPPED_FILE, "w", encoding="utf-8") as f:
        json.dump(dropped_products, f, ensure_ascii=False, indent=2)

    print("\n=== RIEPILOGO INGESTIONE SANITIZZATA ===")
    print(f"Profumi salvati in {OUTPUT_FILE}: {len(catalog)}")
    print(f"  - Piramidi olfattive estratte:  {pyramids_found}/{len(catalog)}")
    print(f"  - Famiglie olfattive rilevate: {families_found}/{len(catalog)}")
    print(f"  - Tipologie (ptype) rilevate:  {ptypes_found}/{len(catalog)}")
    print(f"  - Profili d'uso rilevati:       {usage_found}/{len(catalog)}")
    print(f"Articoli scartati in {DROPPED_FILE}: {len(dropped_products)}")


if __name__ == "__main__":
    main()