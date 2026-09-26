import os
import re
import json
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
from openai import OpenAI

try:
    from src.search import FragranceSearchEngine
except ModuleNotFoundError:
    from search import FragranceSearchEngine

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = BASE_DIR / "data" / "catalog.json"

# ==============================================================================
# MAPPATURA MACRO-CATEGORIE E FAMIGLIE OLFATTIVE DEL PERCORSO GUIDATO
# ==============================================================================
MACRO_FAMILIES = {
    "🍋 Fresco o Agrumato": ["Acquatica", "Agrumata", "Aromatica", "Verde"],
    "🌸 Floreale o Fruttato": ["Floreale", "Floreale - sample", "Fruttata", "Talcata"],
    "🍦 Dolce o Caldo": ["Ambrata", "Gourmand", "Orientale", "Vanigliata"],
    "🪵 Legnoso o Intenso": ["Chypre", "Cuoiata", "Legnosa", "Muschiata", "Speziata", "Tabaccosa"]
}

GUIDED_STEPS = {
    1: {
        "question": "Che tipo di sensazione o famiglia olfattiva preferisci?",
        "options": [
            "🍋 Fresco o Agrumato",
            "🌸 Floreale o Fruttato",
            "🍦 Dolce o Caldo",
            "🪵 Legnoso o Intenso"
        ]
    },
    2: {
        "question": "Per chi stai scegliendo la fragranza?",
        "options": ["Per Lui", "Per Lei", "Unisex"]
    },
    3: {
        "question": "In quale contesto o stagione desideri indossarlo principalmente?",
        "options": ["Tutti i giorni / Ufficio", "Serata speciale o elegante", "Primavera / Estate", "Autunno / Inverno"]
    },
    4: {
        "question": "Hai una preferenza sul budget o intensità?",
        "options": [
            "Accessibile (sotto 120€)",
            "Profumeria Artistica (120€ - 200€)",
            "Alta Gamma & Estratti (oltre 200€)",
            "Nessun limite di budget"
        ]
    }
}

CANONICAL_NOTES = [
    "cannella", "vaniglia", "oud", "tabacco", "rosa", "iris", "gelsomino",
    "ambra", "bergamotto", "limone", "arancia", "cedro", "sandalo", "vetiver",
    "patchouli", "tonka", "pepe", "incenso", "cacao", "caffè", "caffe",
    "mandorla", "fico", "sale", "mirra", "lavanda", "neroli", "tuberosa",
    "pesca", "mela", "pompelmo", "cuoio", "zenzero", "zafferano", "miele",
    "caramello", "muschio", "musk", "eliotropio", "ribes", "menta", "anice",
    "cocco", "lampone", "cardamomo", "chiodi di garofano", "noce moscata"
]

# Blacklist di preposizioni, articoli e termini comuni per evitare falsi positivi
STOPWORDS_NOTES = {
    "alla", "allo", "alle", "agli", "dalla", "dallo", "delle", "degli", "della",
    "nella", "nello", "nelle", "negli", "sulla", "sullo", "sulle", "sugli",
    "dell", "all", "nell", "sull", "come", "dove", "anche", "sono", "cosa",
    "molto", "poco", "più", "meno", "profumo", "fragranza", "odore", "aroma",
    "note", "nota", "testa", "cuore", "fondo", "piramide", "invernale", "estivo",
    "primaverile", "autunnale", "inverno", "estate", "primavera", "autunno",
    "per", "lui", "lei", "uomo", "donna", "unisex", "caldo", "freddo", "giorno",
    "sera", "notte", "giornata", "ufficio", "speciale", "elegante", "tutti",
    "prezzo", "costo", "euro", "budget", "alta", "bassa", "gamma", "accordo", "accordi"
}


class FragranceAdvisor:
    def __init__(self):
        self.search_engine = FragranceSearchEngine()
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ValueError("GROQ_API_KEY mancante nel file .env")

        self.client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key
        )

        self.sessions = defaultdict(list)
        self.active_perfumes = {}
        # session_id -> {"step": None|1|2|3|4, "answers": []}
        self.guided_states = defaultdict(lambda: {"step": None, "answers": []})

        self.catalog_products = []
        self.catalog_notes = set()

        if CATALOG_PATH.exists():
            try:
                with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                    self.catalog_products = json.load(f)

                # Indicizzazione interna delle sole note valide, filtrando le stopword
                for prod in self.catalog_products:
                    pyr = prod.get("olfactory_pyramid", {})
                    for note in pyr.get("top", []) + pyr.get("heart", []) + pyr.get("base", []):
                        n_clean = note.lower().strip()
                        if len(n_clean) >= 3 and n_clean not in STOPWORDS_NOTES:
                            self.catalog_notes.add(n_clean)
                            for w in re.findall(r"\b[a-zA-Zàèéìòù]+\b", n_clean):
                                if len(w) >= 4 and w not in STOPWORDS_NOTES:
                                    self.catalog_notes.add(w)

            except Exception as e:
                print(f"[ADVISOR] Avviso: caricamento catalog.json fallito: {e}")

    def _resolve_macro_family(self, family_ans: str) -> tuple[str, list[str]]:
        """Riconosce la macro-categoria scelta e restituisce le relative sotto-famiglie."""
        ans_clean = family_ans.lower().strip()

        for macro_key, sub_fams in MACRO_FAMILIES.items():
            if macro_key.lower() == ans_clean or macro_key.lower() in ans_clean:
                return macro_key, sub_fams

        if any(w in ans_clean for w in ["fresc", "agrum", "acquat", "aromat", "verd"]):
            return "🍋 Fresco o Agrumato", MACRO_FAMILIES["🍋 Fresco o Agrumato"]
        if any(w in ans_clean for w in ["floreal", "fruttat", "talcat", "fior"]):
            return "🌸 Floreale o Fruttato", MACRO_FAMILIES["🌸 Floreale o Fruttato"]
        if any(w in ans_clean for w in ["dolc", "cald", "gourmand", "vanigli", "ambrat", "oriental"]):
            return "🍦 Dolce o Caldo", MACRO_FAMILIES["🍦 Dolce o Caldo"]
        if any(w in ans_clean for w in ["legnos", "intens", "speziat", "cuoi", "chypre", "tabacc", "muschi"]):
            return "🪵 Legnoso o Intenso", MACRO_FAMILIES["🪵 Legnoso o Intenso"]

        return family_ans, [family_ans]

    def _find_mentioned_product(self, query: str) -> dict | None:
        """Individua se nella frase è presente il nome di un profumo a catalogo."""
        if not self.catalog_products:
            return None

        q_clean = " " + re.sub(r"[?!.,;:\"\'\(\)]", " ", query.lower()) + " "

        for prod in self.catalog_products:
            raw_name = prod.get("name", "").strip()
            if not raw_name:
                continue

            norm_name = re.sub(r"\b\d+\s*ml\b", "", raw_name, flags=re.I)
            norm_name = re.sub(r"\b(eau de parfum|extrait de parfum|edp|edt|millésime)\b", "", norm_name, flags=re.I)
            norm_name = re.sub(r"[?!.,;:\"\'\(\)]", " ", norm_name).strip().lower()
            norm_name = re.sub(r"\s+", " ", norm_name)

            if len(norm_name) >= 3 and f" {norm_name} " in q_clean:
                return {
                    "name": prod.get("name", ""),
                    "brand": prod.get("brand", "Profumeria Artistica"),
                    "price": float(prod.get("price", 0.0)),
                    "family": prod.get("family", ""),
                    "ptype": prod.get("ptype", ""),
                    "add_to_cart_url": prod.get("urls", {}).get("add_to_cart", ""),
                    "product_page_url": prod.get("urls", {}).get("product_page", ""),
                    "image_url": prod.get("urls", {}).get("image_url", ""),
                    "document": prod.get("semantic_text", prod.get("description", ""))
                }

        return None

    def _has_explicit_olfactory_redirect(self, query: str) -> bool:
        """Verifica se l'utente ha esplicitamente richiesto una nuova famiglia olfattiva o note specifiche."""
        q_lower = query.lower()
        if any(term in q_lower for term in CANONICAL_NOTES):
            return True
        scent_terms = ["agrumat", "fresc", "acquat", "marin", "aromat", "verd", "floreal", "dolc", "cald", "gourmand", "legnos", "speziat", "cuoi"]
        return any(term in q_lower for term in scent_terms)

    def _extract_target_notes(self, query: str) -> list[str]:
        """Estrae le note olfattive o materie prime richieste esplicitamente nella query, depurate da stopword."""
        q_lower = f" {query.lower()} "
        found = []

        for note in CANONICAL_NOTES:
            if note not in STOPWORDS_NOTES and re.search(rf"\b{re.escape(note)}\b", q_lower):
                found.append(note)

        for note in self.catalog_notes:
            if len(note) >= 3 and note not in STOPWORDS_NOTES and re.search(rf"\b{re.escape(note)}\b", q_lower):
                if note not in found:
                    found.append(note)

        return found

    def _find_keyword_matches(self, target_notes: list[str], min_price: float | None, max_price: float | None, query: str, limit: int = 4) -> list[dict]:
        """Ricerca ibrida: individua nel catalogo le fragranze che contengono letteralmente la nota richiesta."""
        if not target_notes or not self.catalog_products:
            return []

        scored_candidates = []
        q_lower = query.lower()

        req_season = None
        if any(w in q_lower for w in ["invern", "autunn", "fredd"]):
            req_season = "Autunno / Inverno"
        elif any(w in q_lower for w in ["estiv", "primaver", "cald"]):
            req_season = "Primavera / Estate"

        for prod in self.catalog_products:
            price = float(prod.get("price", 0.0))
            if min_price is not None and price < min_price:
                continue
            if max_price is not None and price > max_price:
                continue

            score = 0
            pyr = prod.get("olfactory_pyramid", {})
            all_notes = [n.lower() for n in pyr.get("top", []) + pyr.get("heart", []) + pyr.get("base", [])]
            semantic = prod.get("semantic_text", "").lower()
            name = prod.get("name", "").lower()
            family = prod.get("family", "").lower()

            matches_count = 0
            for t_note in target_notes:
                if any(t_note in n for n in all_notes):
                    score += 35
                    matches_count += 1
                elif t_note in family:
                    score += 20
                    matches_count += 1
                elif t_note in name:
                    score += 25
                    matches_count += 1
                elif t_note in semantic:
                    score += 10
                    matches_count += 1

            if matches_count == 0:
                continue

            if req_season:
                prod_season = self._detect_season(prod.get("family", ""), prod.get("tags", []), prod.get("usage_profile", ""), prod.get("description", ""))
                if prod_season == req_season:
                    score += 15
                elif prod_season == "Quattro Stagioni":
                    score += 8
                else:
                    score -= 15

            scored_candidates.append((score, prod))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        results = []
        for _, p in scored_candidates[:limit]:
            results.append({
                "name": p.get("name", ""),
                "brand": p.get("brand", "Profumeria Artistica"),
                "price": float(p.get("price", 0.0)),
                "family": p.get("family", ""),
                "ptype": p.get("ptype", ""),
                "add_to_cart_url": p.get("urls", {}).get("add_to_cart", ""),
                "product_page_url": p.get("urls", {}).get("product_page", ""),
                "image_url": p.get("urls", {}).get("image_url", ""),
                "document": p.get("semantic_text", p.get("description", ""))
            })
        return results

    def _detect_gender(self, name: str, tags: list, usage_profile: str = "", description: str = "") -> str:
        """Determina il genere del profumo senza allucinazioni da sottostringa né priorità errate."""
        name_lower = name.lower()
        tags_lower = [t.strip().lower() for t in tags]
        u_prof_lower = (usage_profile or "").lower()
        desc_lower = (description or "").lower()
        combined_text = f"{u_prof_lower} {desc_lower}"

        if re.search(r"\b(for\s+her|pour\s+femme|woman|women)\b", name_lower):
            return "Per Lei"
        if re.search(r"\b(for\s+him|pour\s+homme|for\s+men)\b", name_lower) or (
            re.search(r"\b(man|homme|uomo)\b", name_lower) and not re.search(r"\b(woman|women|mandorla)\b", name_lower)
        ):
            return "Per Lui"

        has_unisex_tag = any(re.search(r"\bunisex\b", t, re.I) for t in tags_lower)
        has_lui_tag = any(re.search(r"\b(per\s+lui|uomo|maschile|pour\s+homme|for\s+men)\b", t, re.I) for t in tags_lower)
        has_lei_tag = any(re.search(r"\b(per\s+lei|donna|femminile|pour\s+femme|for\s+women|for\s+her)\b", t, re.I) for t in tags_lower)

        has_unisex_text = bool(re.search(r"\b(unisex|sia per uomo che per donna|uomo e donna)\b", combined_text, re.I))
        has_lui_text = bool(re.search(r"\b(maschile|per lui|da uomo|all[' ]uomo|per l[' ]uomo)\b", combined_text, re.I))
        has_lei_text = bool(re.search(r"\b(femminile|per lei|da donna|alla donna|per la donna)\b", combined_text, re.I))

        if has_unisex_tag or has_unisex_text or (has_lui_tag and has_lei_tag) or (has_lui_text and has_lei_text):
            return "Unisex"
        if (has_lui_tag or has_lui_text) and not (has_lei_tag or has_lei_text):
            return "Per Lui"
        if (has_lei_tag or has_lei_text) and not (has_lui_tag or has_lui_text):
            return "Per Lei"

        return "Unisex"

    def _detect_season(self, family: str, tags: list, usage_profile: str = "", description: str = "") -> str:
        """Determina la stagionalità o contesto ideale senza sovrascritture casuali."""
        tags_lower = [t.strip().lower() for t in tags]
        u_prof_lower = (usage_profile or "").lower()
        desc_lower = (description or "").lower()
        combined_text = f"{' '.join(tags_lower)} {u_prof_lower} {desc_lower}"

        has_inverno = bool(re.search(r"\b(invern\w*|autunn\w*|fredd\w*)\b", combined_text, re.I))
        has_estate = bool(re.search(r"\b(estiv\w*|estate|primaver\w*|cald\w*)\b", combined_text, re.I))
        has_4stagioni = bool(re.search(r"\b(quattro\s+stagioni|tutte\s+le\s+stagioni|tutto\s+l[' ]anno|versatile|ogni\s+stagione)\b", combined_text, re.I))

        if has_4stagioni or (has_inverno and has_estate):
            return "Quattro Stagioni"
        if has_inverno and not has_estate:
            return "Autunno / Inverno"
        if has_estate and not has_inverno:
            return "Primavera / Estate"

        fam_lower = (family or "").lower()
        if any(f in fam_lower for f in ["acquat", "agrum", "marin", "verd", "ozonat"]):
            return "Primavera / Estate"
        if any(f in fam_lower for f in ["cuoi", "tabacc", "ambrat", "gourmand", "oriental", "speziat", "vanigli"]):
            return "Autunno / Inverno"

        return "Quattro Stagioni"

    def _is_compatible_with_guided(self, prod_enriched: dict, gender_req: str, occasion_req: str) -> bool:
        """Valida deterministicamente la compatibilità con le scelte dell'utente nel percorso guidato."""
        traits = prod_enriched.get("traits", "")
        parts = [p.strip() for p in traits.split("•")]
        prod_gender = parts[1] if len(parts) > 1 else "Unisex"
        prod_season = parts[2] if len(parts) > 2 else "Quattro Stagioni"

        if "lui" in gender_req.lower():
            if prod_gender == "Per Lei":
                return False
        elif "lei" in gender_req.lower():
            if prod_gender == "Per Lui":
                return False

        occ_lower = occasion_req.lower()
        if "primaver" in occ_lower or "estat" in occ_lower:
            if prod_season == "Autunno / Inverno":
                return False
        elif "invern" in occ_lower or "autunn" in occ_lower:
            if prod_season == "Primavera / Estate":
                return False

        return True

    def _enrich_product_payload(self, prod_dict: dict, card_type: str = "slideover") -> dict:
        """Estrae e organizza gli attributi per la Product Card."""
        p_name = prod_dict.get("name", "").strip()
        p_brand = prod_dict.get("brand", "Profumeria Artistica").strip()
        p_price = float(prod_dict.get("price", 0.0) or 0.0)
        p_family = prod_dict.get("family", "").strip()
        p_ptype = prod_dict.get("ptype", "").strip() or "Profumo Artistico"
        p_cart = prod_dict.get("add_to_cart_url", "")
        p_page = prod_dict.get("product_page_url", "")
        p_img = prod_dict.get("image_url", "")

        cat_match = None
        for cp in self.catalog_products:
            if cp.get("name", "").strip().lower() == p_name.lower():
                cat_match = cp
                break

        key_notes = []
        story = ""
        traits = ""

        if cat_match:
            p_page = cat_match.get("urls", {}).get("product_page", "") or p_page

            pyr = cat_match.get("olfactory_pyramid", {})
            top = [n.strip() for n in pyr.get("top", []) if n.strip()][:2]
            heart = [n.strip() for n in pyr.get("heart", []) if n.strip()][:2]
            base = [n.strip() for n in pyr.get("base", []) if n.strip()][:2]
            key_notes = list(dict.fromkeys(top + heart + base))[:6]

            if not key_notes and cat_match.get("family"):
                key_notes = [f.strip() for f in cat_match["family"].split(",") if f.strip()][:4]

            clean_ptype = cat_match.get("ptype") or p_ptype
            if not clean_ptype or clean_ptype.lower() in ["profumo artistico", "profumo", "fragranza"]:
                n_low = p_name.lower()
                if "extrait" in n_low:
                    clean_ptype = "Extrait de Parfum"
                elif "eau de parfum" in n_low or "edp" in n_low:
                    clean_ptype = "Eau de Parfum"
                elif "eau de toilette" in n_low or "edt" in n_low:
                    clean_ptype = "Eau de Toilette"
                elif "cologne" in n_low:
                    clean_ptype = "Eau de Cologne"
                else:
                    clean_ptype = "Profumo Artistico"

            tags = cat_match.get("tags", [])
            u_prof = cat_match.get("usage_profile", "")
            desc = cat_match.get("description", "")
            fam = cat_match.get("family", "") or p_family

            gender_trait = self._detect_gender(p_name, tags, u_prof, desc)
            season_trait = self._detect_season(fam, tags, u_prof, desc)

            traits = f"{clean_ptype} • {gender_trait} • {season_trait}"

            raw_text = cat_match.get("description", "")
            cleaned = re.sub(rf"^Profumo\s+{re.escape(p_name)}.*?\.\s*", "", raw_text, flags=re.I)
            cleaned = re.sub(r"\bformato\s*:\s*[^\.\n]+", "", cleaned, flags=re.I)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()

            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', cleaned) if len(s.strip()) > 15]

            candidate = None
            for s in sentences:
                s_clean = s.strip()
                if 30 <= len(s_clean) <= 130:
                    candidate = s_clean.rstrip(".!?") + "."
                    break

            if candidate:
                story = candidate
            else:
                if u_prof and 30 <= len(u_prof) <= 130:
                    story = u_prof.rstrip(".!?") + "."
                else:
                    notes_preview = ", ".join(key_notes[:3]) if key_notes else ""
                    fam_clean = p_family.lower() if p_family else "artistica"
                    if notes_preview:
                        story = f"Un'armonia {fam_clean} costruita attorno ad accordi di {notes_preview}, per una presenza elegante e distintiva."
                    else:
                        story = f"Una raffinata creazione {fam_clean} dall'accordo avvolgente, concepita per lasciare una presenza memorabile."

        else:
            key_notes = [f.strip() for f in p_family.split(",") if f.strip()][:4]
            story = f"Una creazione {p_family.lower() or 'artistica'} d'eccellenza, equilibrata ed elegante sulla pelle."
            gender_trait = self._detect_gender(p_name, [], "", prod_dict.get("document", ""))
            season_trait = self._detect_season(p_family, [], "", prod_dict.get("document", ""))
            traits = f"{p_ptype} • {gender_trait} • {season_trait}"

        return {
            "name": p_name,
            "brand": p_brand,
            "price": p_price,
            "family": p_family,
            "ptype": p_ptype,
            "add_to_cart_url": p_cart,
            "product_page_url": p_page,
            "image_url": p_img,
            "card_type": card_type,
            "story": story,
            "key_notes": key_notes,
            "traits": traits,
            "description": story
        }

    def _extract_price_constraints(self, query: str, active_perfume: dict | None) -> tuple[float | None, float | None, str]:
        """Estrae vincoli di budget relativi o assoluti e ripulisce la query semantica."""
        min_p = None
        max_p = None
        q = query.strip()

        is_cheaper = bool(re.search(r"\b(pi[uù]\s+economic[oa]|meno\s+costos[oa]|pi[uù]\s+abbordabile|pi[uù]\s+accessibile|spendere\s+meno|a\s+meno|costa\s+meno)\b", q, re.I))
        is_expensive = bool(re.search(r"\b(pi[uù]\s+costos[oa]|pi[uù]\s+pregiat[oa]|di\s+fascia\s+pi[uù]\s+alta|pi[uù]\s+esclusiv[oa]|di\s+lusso|alta\s+gamma|alta\s+profumeria|spendere\s+di\s+pi[uù])\b", q, re.I))

        if is_cheaper and active_perfume and active_perfume.get("price"):
            current_price = float(active_perfume["price"])
            max_p = max(0.0, current_price - 0.5)
        elif is_expensive and active_perfume and active_perfume.get("price"):
            current_price = float(active_perfume["price"])
            min_p = current_price + 0.5

        range_match = re.search(r"\b(?:tra|da)\s+(?:i\s+)?(\d+(?:[.,]\d+)?)\s*(?:€|euro)?\s+(?:e|a)\s+(?:i\s+)?(\d+(?:[.,]\d+)?)\s*(?:€|euro)?\b", q, re.I)
        if range_match:
            min_p = float(range_match.group(1).replace(",", "."))
            max_p = float(range_match.group(2).replace(",", "."))

        max_match = re.search(r"\b(?:sotto\s+(?:i\s+)?|meno\s+di\s+|massimo\s+|max\s+|entro\s+(?:i\s+)?|fino\s+a\s+|budget\s+(?:di\s+)?|<|<=)\s*(\d+(?:[.,]\d+)?)\s*(?:€|euro)?\b", q, re.I)
        if max_match and not range_match:
            val = float(max_match.group(1).replace(",", "."))
            max_p = val if max_p is None else min(max_p, val)

        min_match = re.search(r"\b(?:sopra\s+(?:i\s+)?|oltre\s+(?:i\s+)?|pi[uù]\s+di\s+|almeno\s+|minimo\s+|min\s+|>|>=)\s*(\d+(?:[.,]\d+)?)\s*(?:€|euro)?\b", q, re.I)
        if min_match and not range_match:
            val = float(min_match.group(1).replace(",", "."))
            min_p = val if min_p is None else max(min_p, val)

        search_query = q
        search_query = re.sub(r"\b(?:tra|da)\s+(?:i\s+)?\d+(?:[.,]\d+)?\s*(?:€|euro)?\s+(?:e|a)\s+(?:i\s+)?\d+(?:[.,]\d+)?\s*(?:€|euro)?\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b(?:sotto\s+(?:i\s+)?|meno\s+di\s+|massimo\s+|max\s+|entro\s+(?:i\s+)?|fino\s+a\s+|budget\s+(?:di\s+)?|<|<=)\s*\d+(?:[.,]\d+)?\s*(?:€|euro)?\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b(?:sopra\s+(?:i\s+)?|oltre\s+(?:i\s+)?|pi[uù]\s+di\s+|almeno\s+|minimo\s+|min\s+|>|>=)\s*\d+(?:[.,]\d+)?\s*(?:€|euro)?\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b\d+\s*(?:€|euro)\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b(pi[uù]\s+economic[oa]|meno\s+costos[oa]|pi[uù]\s+abbordabile|pi[uù]\s+accessibile|spendere\s+meno|a\s+meno)\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b(pi[uù]\s+costos[oa]|pi[uù]\s+pregiat[oa]|di\s+fascia\s+pi[uù]\s+alta|pi[uù]\s+esclusiv[oa]|di\s+lusso|alta\s+gamma|alta\s+profumeria|spendere\s+di\s+pi[uù])\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\s+", " ", search_query).strip()

        stopwords = [
            "vorrei", "cerco", "cercami", "cercavo", "trova", "trovami", "consiglia",
            "consigliami", "profumo", "fragranza", "alternativa", "alternative", "altro",
            "altra", "altri", "altre", "opzione", "opzioni", "simile", "simili",
            "cambia", "cambiamo", "qualcos", "qualcosa"
        ]
        words = [w for w in re.findall(r"\b[a-zA-Zàèéìòù]+\b", search_query.lower()) if len(w) > 2 and w not in stopwords]

        if not words and active_perfume:
            fam = active_perfume.get("family", "")
            search_query = f"Profumo {fam} affine a {active_perfume['name']}"

        return min_p, max_p, search_query

    def _determine_intent(self, query: str, active_perfume: dict) -> str:
        if not active_perfume:
            return "CAMBIA"

        q = re.sub(r"[?!.,;:]", " ", query.lower()).strip()

        switch_patterns = [
            r"\b(pi[uù]\s+economic[oa]|meno\s+costos[oa]|pi[uù]\s+abbordabile|pi[uù]\s+accessibile|spendere\s+meno|a\s+meno|costa\s+meno)\b",
            r"\b(pi[uù]\s+costos[oa]|pi[uù]\s+pregiat[oa]|alta\s+gamma|spendere\s+di\s+pi[uù])\b",
            r"\b(?:sotto\s+i?|meno\s+di|entro\s+i?|fino\s+a|oltre\s+i?|pi[uù]\s+di|budget\s+di?)\s*\d+\b",
            r"\b(?:tra|da)\s+\d+.*\b(?:e|a)\s+\d+\b",
            r"\b(vorrei|voglio|cerco|cercavo|cercami|trova|trovami|proponi|proponimi)\s+qualcosa\b",
            r"\bqualcosa\s+con\b", r"\bqualcosa\s+di\b",
            r"\bqualcos[' ]altro\b", r"\bqualcosa\s+d[' ]altr[oa]\b",
            r"\b(vorrei|voglio|cerco|cercavo|cerca|cercami|trova|trovami|consiglia|consigliami|mostra|mostrami|proponi|proponimi|suggerisci|suggeriscimi)\b.*\b(un|una|uno|profumo|fragranza|note|accordo|flacone|alternativa)\b",
            r"\bun\s+altr[oa]\b", r"\bun[' ]altra\b",
            r"\baltr[oaei]\s+profum[ie]\b", r"\baltr[oaei]\s+fragranz[ea]\b",
            r"\b(mostra|mostrami|consiglia|consigliami|trova|trovami|cerca|cercami|proponi|proponimi)\s+altr[oa]\b",
            r"\bcambia\s+profumo\b", r"\bcambiamo\b", r"\bpassiamo\s+a\b",
            r"\balternativa\b", r"\balternative\b", r"\bdivers[oaei]\b"
        ]
        if any(re.search(p, q) for p in switch_patterns):
            return "CAMBIA"

        stay_patterns = [
            r"\b(le|quali|che|su[oaei])\s+note\b",
            r"\bnote\s+di\s+(testa|cuore|fondo)\b",
            r"\b(ha|contiene)\s+note\b",
            r"\bpiramide\b", r"\bcomposizione\b",
            r"\b(quali|che)\s+ingredienti\b",
            r"\bsu[oaei]\b",
            r"\bquest[oaei]\b",
            r"\blo\s+posso\b", r"\bla\s+posso\b", r"\bsi\s+pu[oò]\b",
            r"\b(quanto\s+costa|qual\s+[eè]\s+il\s+prezzo|quanto\s+viene|costo\s+effettivo|[eè]\s+costos[oa])\b",
            r"^\s*(prezzo|costo)\s*\??\s*$",
            r"\b(quanto\s+dura|durata|persistenza|proiezione|sillage|scia)\b",
            r"\b(va\s+bene|è\s+adatt[oa]|adatt[oa]\s+a)\b",
            r"\b(per\s+l'ufficio|in\s+ufficio|al\s+lavoro)\b",
            r"\b(di\s+giorno|di\s+sera|a\s+cena|a\s+pranzo)\b",
            r"\b(in\s+spiaggia|al\s+mare|in\s+palestra)\b",
            r"\b(estiv[oae]|invernal[ei]|primaveril[ei]|autunnal[ei])\b"
        ]
        if any(re.search(p, q) for p in stay_patterns):
            return "VALUTA"

        prompt = (
            f"Stiamo parlando del profumo: '{active_perfume['name']}' ({active_perfume.get('brand', '')}).\n"
            f"Messaggio del cliente: \"{query}\"\n\n"
            "Regola:\n"
            "- Rispondi 'CAMBIA' SOLO se il cliente chiede esplicitamente di cercare, mostrare o consigliare un profumo DIVERSO o un'alternativa.\n"
            "- In tutti gli altri casi (domande su note, pareri, chiarimenti, orari, contesti, o frasi dubbie), rispondi 'VALUTA'.\n"
            "Rispondi SOLO con la parola 'VALUTA' o 'CAMBIA'."
        )

        try:
            res = self.client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=4
            )
            decision = res.choices[0].message.content.strip().upper()
            return "CAMBIA" if "CAMBIA" in decision else "VALUTA"
        except Exception:
            return "VALUTA"

    def advise(self, user_query: str, session_id: str = "default", max_price: float = None, step_override: int = None) -> dict:
        if not session_id:
            session_id = "default"

        query_clean = user_query.strip()
        q_lower = query_clean.lower()
        state = self.guided_states[session_id]

        start_guided_triggers = [
            "guidami", "guida", "ricomincia", "riparti",
            "percorso guidato", "ricomincia percorso", "inizia guida"
        ]
        if any(t in q_lower for t in start_guided_triggers):
            state["step"] = 1
            state["answers"] = []
            self.active_perfumes[session_id] = None
            return {
                "reply": "Perfetto! Ripartiamo con 4 brevi domande per selezionare le fragranze ideali per te.\n\n" + GUIDED_STEPS[1]["question"],
                "options": GUIDED_STEPS[1]["options"],
                "products": [],
                "step": 1,
                "mode": "guided"
            }

        start_free_triggers = [
            "chiedi liberamente", "fai una domanda libera", "domanda libera",
            "chat libera", "parla liberamente"
        ]
        if any(t in q_lower for t in start_free_triggers):
            state["step"] = None
            state["answers"] = []
            return {
                "reply": "Certamente! Dimmi pure: quale fragranza, nota olfattiva o sensazione stai cercando?",
                "options": [],
                "products": [],
                "step": None,
                "mode": "free"
            }

        effective_step = step_override if step_override is not None else state["step"]

        if effective_step is not None:
            if effective_step == 1:
                state["answers"] = [query_clean]
                state["step"] = 2
                return {
                    "reply": GUIDED_STEPS[2]["question"],
                    "options": GUIDED_STEPS[2]["options"],
                    "products": [],
                    "step": 2,
                    "mode": "guided"
                }
            elif effective_step == 2:
                ans0 = state["answers"][0] if len(state["answers"]) > 0 else "🍋 Fresco o Agrumato"
                state["answers"] = [ans0, query_clean]
                state["step"] = 3
                return {
                    "reply": GUIDED_STEPS[3]["question"],
                    "options": GUIDED_STEPS[3]["options"],
                    "products": [],
                    "step": 3,
                    "mode": "guided"
                }
            elif effective_step == 3:
                ans0 = state["answers"][0] if len(state["answers"]) > 0 else "🍋 Fresco o Agrumato"
                ans1 = state["answers"][1] if len(state["answers"]) > 1 else "Unisex"
                state["answers"] = [ans0, ans1, query_clean]
                state["step"] = 4
                return {
                    "reply": GUIDED_STEPS[4]["question"],
                    "options": GUIDED_STEPS[4]["options"],
                    "products": [],
                    "step": 4,
                    "mode": "guided"
                }
            elif effective_step == 4:
                ans0 = state["answers"][0] if len(state["answers"]) > 0 else "🍋 Fresco o Agrumato"
                ans1 = state["answers"][1] if len(state["answers"]) > 1 else "Unisex"
                ans2 = state["answers"][2] if len(state["answers"]) > 2 else "Tutti i giorni"
                state["answers"] = [ans0, ans1, ans2, query_clean]
                state["step"] = None
                return self._generate_guided_recommendations(state["answers"], session_id)

        return self._handle_free_chat(user_query, session_id, max_price)

    def _generate_guided_recommendations(self, answers: list, session_id: str) -> dict:
        family_raw = answers[0] if len(answers) > 0 else "🍋 Fresco o Agrumato"
        gender = answers[1] if len(answers) > 1 else "Unisex"
        occasion = answers[2] if len(answers) > 2 else "Tutti i giorni"
        budget_str = answers[3] if len(answers) > 3 else "Nessun limite"

        macro_label, sub_fams = self._resolve_macro_family(family_raw)
        sub_fams_str = ", ".join(sub_fams)
        clean_macro = re.sub(r"^[^\w\s]+", "", macro_label).strip()

        print(f"[GUIDED SEARCH] Macro: '{macro_label}' ({sub_fams}) | Destinatario: '{gender}' | Occasione: '{occasion}' | Budget: '{budget_str}'")

        min_p = None
        max_p = None

        if "sotto 120" in budget_str.lower() or "< 120" in budget_str:
            max_p = 120.0
        elif "120" in budget_str and "200" in budget_str:
            min_p = 120.0
            max_p = 200.0
        elif "oltre 200" in budget_str.lower() or "> 200" in budget_str:
            min_p = 200.0

        search_prompt = (
            f"Profumo {clean_macro} appartenente a famiglie come {sub_fams_str}. "
            f"Fragranza destinata a {gender}. Ideale per contesto {occasion}."
        )

        results = self.search_engine.search(
            query=search_prompt,
            min_price=min_p,
            max_price=max_p,
            n_results=12
        )

        structured_products = []
        first_product = None

        if results["ids"] and len(results["ids"][0]) > 0:
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i]
                doc = results["documents"][0][i]

                prod_data = {
                    "name": meta.get("name", ""),
                    "brand": meta.get("brand", "Profumeria Artistica"),
                    "price": float(meta.get("price", 0.0)),
                    "family": meta.get("family", ""),
                    "ptype": meta.get("ptype", ""),
                    "add_to_cart_url": meta.get("add_to_cart_url", ""),
                    "product_page_url": meta.get("product_page_url", ""),
                    "image_url": meta.get("image_url", ""),
                    "document": doc
                }

                enriched = self._enrich_product_payload(prod_data, card_type="slideover")
                is_compat = self._is_compatible_with_guided(enriched, gender, occasion)

                if is_compat:
                    structured_products.append(enriched)
                    if len(structured_products) == 1:
                        first_product = prod_data
                    if len(structured_products) == 3:
                        break

            if len(structured_products) < 3:
                for i in range(len(results["ids"][0])):
                    meta = results["metadatas"][0][i]
                    p_name = meta.get("name", "")
                    if any(p["name"].lower() == p_name.lower() for p in structured_products):
                        continue

                    doc = results["documents"][0][i]
                    prod_data = {
                        "name": meta.get("name", ""),
                        "brand": meta.get("brand", "Profumeria Artistica"),
                        "price": float(meta.get("price", 0.0)),
                        "family": meta.get("family", ""),
                        "ptype": meta.get("ptype", ""),
                        "add_to_cart_url": meta.get("add_to_cart_url", ""),
                        "product_page_url": meta.get("product_page_url", ""),
                        "image_url": meta.get("image_url", ""),
                        "document": doc
                    }
                    enriched = self._enrich_product_payload(prod_data, card_type="slideover")
                    traits_parts = [p.strip() for p in enriched.get("traits", "").split("•")]
                    p_gen = traits_parts[1] if len(traits_parts) > 1 else "Unisex"

                    if ("lui" in gender.lower() and p_gen == "Per Lei") or ("lei" in gender.lower() and p_gen == "Per Lui"):
                        continue

                    structured_products.append(enriched)
                    if len(structured_products) == 1:
                        first_product = prod_data
                    if len(structured_products) == 3:
                        break

        if not structured_products:
            return {
                "reply": f"Non ho trovato fragranze a catalogo che rientrino esattamente nella categoria '{macro_label}' per {gender} nella fascia di prezzo selezionata. Prova a scegliere un'altra combinazione!",
                "options": ["🎯 Ricomincia percorso guidato", "💬 Fai una domanda libera"],
                "products": [],
                "step": None,
                "mode": "free"
            }

        if first_product:
            self.active_perfumes[session_id] = first_product

        prompt = (
            f"L'utente ha completato il percorso guidato con queste preferenze:\n"
            f"- Macro-categoria olfattiva: {macro_label}\n"
            f"- Destinatario: {gender}\n"
            f"- Occasione/Uso: {occasion}\n"
            f"- Fascia Budget: {budget_str}\n\n"
            "COMPITO MAÎTRE PARFUMEUR:\n"
            "Formula un'introduzione raffinata ed elegante (massimo 1-2 frasi) da Maître Parfumeur "
            "per presentare la selezione di fragranze d'autore ricavate dal catalogo per rispecchiare i suoi desideri.\n"
            "NON elencare prezzi o link (saranno visualizzati direttamente nelle schede prodotto sottostanti)."
        )

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        reply = response.choices[0].message.content.strip()

        self.sessions[session_id].append({"role": "user", "content": f"Percorso guidato completato: {macro_label}, {gender}, {occasion}, {budget_str}"})
        self.sessions[session_id].append({"role": "assistant", "content": reply})

        return {
            "reply": reply,
            "options": ["🎯 Ricomincia percorso guidato", "💬 Fai una domanda libera"],
            "products": structured_products,
            "step": None,
            "mode": "free"
        }

    def _handle_free_chat(self, user_query: str, session_id: str, max_price: float) -> dict:
        history = self.sessions[session_id]
        active_before = self.active_perfumes.get(session_id)

        mentioned_product = self._find_mentioned_product(user_query)
        is_new_product_switch = False

        if mentioned_product:
            if not active_before or active_before.get("name") != mentioned_product.get("name"):
                is_new_product_switch = True
            self.active_perfumes[session_id] = mentioned_product
            print(f"[ENTITY MATCH] '{mentioned_product['name']}' (Nuovo switch: {is_new_product_switch})")

        # RAMO 1: Profumo citato per nome per la prima volta
        if is_new_product_switch and mentioned_product:
            context_str = (
                f"[PRODOTTO RICHIESTO DAL CLIENTE]\n"
                f"- Nome: {mentioned_product['name']}\n"
                f"- Brand: {mentioned_product.get('brand', 'Profumeria Artistica')}\n"
                f"- Tipologia: {mentioned_product.get('ptype', '')} | Famiglia: {mentioned_product.get('family', '')}\n"
                f"- Prezzo di vendita ufficiale: {mentioned_product['price']} EUR\n"
                f"- Link Acquisto: {mentioned_product['add_to_cart_url']}\n"
                f"- Profilo olfattivo, note ed evoluzione: {mentioned_product['document']}"
            )

            system_prompt = (
                "Sei un Maitre Parfumeur raffinato ed esperto di una boutique di profumeria artistica.\n"
                "L'utente ha chiesto espressamente informazioni su questo specifico profumo presente a catalogo.\n\n"
                "REGOLE TASSATIVE DI RISPOSTA:\n"
                "1. Rispondi alla richiesta dell'utente con eleganza, autorevolezza e precisione descrivendo la fragranza e le note.\n"
                "2. Descrizione raffinata e risposta puntuale alla richiesta del cliente (massimo 2-3 frasi).\n"
                "3. NON inserire link o formattazioni di vendita (verranno mostrati automaticamente nella product card)."
            )

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history[-2:])
            messages.append({"role": "user", "content": f"RICHIESTA UTENTE: {user_query}\n\nCONTESTO:\n{context_str}"})

            response = self.client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                temperature=0.0
            )
            reply = response.choices[0].message.content.strip()

            enriched = self._enrich_product_payload(mentioned_product, card_type="standard")

            self.sessions[session_id].append({"role": "user", "content": user_query})
            self.sessions[session_id].append({"role": "assistant", "content": reply})

            return {"reply": reply, "options": [], "products": [enriched], "step": None, "mode": "free"}

        else:
            active = self.active_perfumes.get(session_id)
            intent = self._determine_intent(user_query, active)
            is_follow_up = (intent == "VALUTA" and active is not None)

            print(f"\n[ROUTER DEBUG] Profumo attivo: '{active.get('name') if active else 'NESSUNO'}'")
            print(f"[ROUTER DEBUG] Domanda: '{user_query}' -> Decisione: {'SEGUI PRODOTTO (VALUTA)' if is_follow_up else 'CERCA NUOVO (CAMBIA)'}")

            # RAMO 2: Chiarimento o approfondimento sullo stesso profumo attivo
            if is_follow_up:
                context_str = (
                    f"[PRODOTTO ATTUALMENTE DISCUSSO]\n"
                    f"- Nome: {active['name']}\n"
                    f"- Brand: {active.get('brand', 'Profumeria Artistica')}\n"
                    f"- Famiglia: {active.get('family', '')} | Tipologia: {active.get('ptype', '')}\n"
                    f"- Prezzo di vendita ufficiale: {active['price']} EUR\n"
                    f"- Link Acquisto: {active['add_to_cart_url']}\n"
                    f"- Profilo olfattivo, note ed occasioni d'uso: {active['document']}"
                )

                system_prompt = (
                    "Sei un Maitre Parfumeur e critico olfattivo di altissimo livello in una boutique di profumeria artistica.\n"
                    "Il tuo dovere principale è l'ONESTÀ e l'AUTOREVOLEZZA PROFESSIONALE: NON fare il compiacente e NON dire di sì a tutto.\n\n"
                    "REGOLE CRITICHE PER IL GIUDIZIO E CHIARIMENTI (BLUF):\n"
                    "1. DECISIONE NETTA NELLA PRIMA FRASE:\n"
                    "   - Se l'utente chiede spiegazioni sulle note o sulla piramide, descrivile con eleganza evidenziando testa, cuore e fondo.\n"
                    "   - Se chiede esplicitamente il prezzo o il costo, indicalo subito.\n"
                    "   - Se la richiesta dell'utente è palesemente inadatta o non compatibile col profumo discusso, sconsiglialo con fermezza ed eleganza.\n"
                    "   - Se invece è adeguata (es. marino/agrumato per l'estate), conferma con sicurezza.\n"
                    "2. MOTIVAZIONE TECNICA IN 1-2 FRASI: Spiega la ragione chimico-olfattiva concreta basandoti sulla piramide e sul contesto d'uso.\n"
                    "3. DIVIETO ASSOLUTO DI RACCOMANDARE ALTRI PROFUMI A MEMORIA:\n"
                    "   - NON citare, NON inventare e NON proporre nomi di altri profumi non presenti in questo contesto.\n"
                    "   - Se il profumo discusso non va bene per le note o l'occasione richiesta, dillo con chiarezza e aggiungi che puoi cercargli una fragranza a catalogo con quelle caratteristiche.\n"
                    "4. GESTIONE DI PREZZO E LINK AL CARRELLO: Inserisci il prezzo solo se richiesto espressamente dall'utente.\n"
                    "5. SINTESI TOTALE: Massimo 3 o 4 frasi concise. Niente testi dispersivi."
                )

                messages = [{"role": "system", "content": system_prompt}]
                messages.extend(history[-2:])
                messages.append({"role": "user", "content": f"RICHIESTA UTENTE: {user_query}\n\nCONTESTO:\n{context_str}"})

                response = self.client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=messages,
                    temperature=0.0
                )
                reply = response.choices[0].message.content.strip()

                self.sessions[session_id].append({"role": "user", "content": user_query})
                self.sessions[session_id].append({"role": "assistant", "content": reply})

                return {"reply": reply, "options": [], "products": [], "step": None, "mode": "free"}

            # RAMO 3: Ricerca Ibrida di un nuovo profumo su ChromaDB + Keyword-Boost depurato da Stopword
            else:
                parsed_min_p, parsed_max_p, search_query_clean = self._extract_price_constraints(user_query, active)

                effective_max_p = parsed_max_p if parsed_max_p is not None else max_price
                effective_min_p = parsed_min_p

                is_seeking_similar_alternative = (active is not None and not self._has_explicit_olfactory_redirect(search_query_clean))

                target_notes = self._extract_target_notes(user_query)
                keyword_matches = []

                if target_notes:
                    keyword_matches = self._find_keyword_matches(
                        target_notes=target_notes,
                        min_price=effective_min_p,
                        max_price=effective_max_p,
                        query=user_query,
                        limit=3
                    )
                    print(f"[HYBRID BOOST] Trovate {len(keyword_matches)} fragranze con note esatte: {target_notes}")

                if is_seeking_similar_alternative and active:
                    active_fam = active.get("family", "")
                    cat_match = next((cp for cp in self.catalog_products if cp.get("name", "").strip().lower() == active.get("name", "").strip().lower()), None)
                    key_notes_list = []
                    if cat_match:
                        pyr = cat_match.get("olfactory_pyramid", {})
                        key_notes_list = pyr.get("top", []) + pyr.get("heart", []) + pyr.get("base", [])

                    notes_str = ", ".join(key_notes_list[:5]) if key_notes_list else active_fam
                    chroma_query = f"Profumo {active_fam}. Note olfattive: {notes_str}. {active.get('document', '')[:120]}"
                    print(f"[ALTERNATIVE SEARCH] Ricerca alternativa affine a '{active['name']}' ({active_fam}) | Note: {notes_str} | Prezzo: min={effective_min_p}, max={effective_max_p}")
                else:
                    chroma_query = search_query_clean
                    print(f"[SEARCH EXEC] Query ChromaDB: '{search_query_clean}' | Prezzo: min={effective_min_p}, max={effective_max_p}")

                results = self.search_engine.search(
                    query=chroma_query,
                    min_price=effective_min_p,
                    max_price=effective_max_p,
                    n_results=10
                )

                candidates_text = []
                candidates_map = {}
                candidate_idx = 1
                seen_names = set()

                # 1. Priorità assoluta ai candidati che contengono le note richieste (Keyword-Boost)
                for km in keyword_matches:
                    p_name_lower = km["name"].strip().lower()
                    if is_seeking_similar_alternative and active and p_name_lower == active.get("name", "").strip().lower():
                        continue
                    if p_name_lower in seen_names:
                        continue

                    pid = f"PRODOTTO_{candidate_idx}"
                    candidates_map[pid] = km
                    seen_names.add(p_name_lower)
                    candidates_text.append(
                        f"[{pid}]\n"
                        f"Nome: {km['name']}\n"
                        f"Brand: {km.get('brand', 'Profumeria Artistica')}\n"
                        f"Tipologia: {km.get('ptype', '')} | Famiglia: {km.get('family', '')}\n"
                        f"Prezzo: {km['price']} EUR\n"
                        f"Descrizione e Note: {km['document']}"
                    )
                    candidate_idx += 1

                # 2. Integrazione con i risultati semantici di ChromaDB
                if results["ids"] and len(results["ids"][0]) > 0:
                    for i in range(len(results["ids"][0])):
                        meta = results["metadatas"][0][i]
                        doc = results["documents"][0][i]
                        p_name_lower = meta.get("name", "").strip().lower()

                        if is_seeking_similar_alternative and active and p_name_lower == active.get("name", "").strip().lower():
                            continue
                        if p_name_lower in seen_names:
                            continue

                        pid = f"PRODOTTO_{candidate_idx}"
                        candidates_map[pid] = {
                            "name": meta.get("name", ""),
                            "brand": meta.get("brand", "Profumeria Artistica"),
                            "price": float(meta.get("price", 0.0)),
                            "family": meta.get("family", ""),
                            "ptype": meta.get("ptype", ""),
                            "add_to_cart_url": meta.get("add_to_cart_url", ""),
                            "product_page_url": meta.get("product_page_url", ""),
                            "image_url": meta.get("image_url", ""),
                            "document": doc
                        }
                        seen_names.add(p_name_lower)
                        candidates_text.append(
                            f"[{pid}]\n"
                            f"Nome: {meta['name']}\n"
                            f"Brand: {meta.get('brand', 'Profumeria Artistica')}\n"
                            f"Tipologia: {meta.get('ptype', '')} | Famiglia: {meta.get('family', '')}\n"
                            f"Prezzo: {meta['price']} EUR\n"
                            f"Descrizione e Note: {doc}"
                        )
                        candidate_idx += 1
                        if candidate_idx > 5:
                            break

                if not candidates_map:
                    if effective_max_p or effective_min_p:
                        filtro_desc = f"sotto i {effective_max_p}€" if effective_max_p else f"sopra i {effective_min_p}€"
                        fallback_reply = (
                            f"Non ho trovato a catalogo un'opzione che rispetti questo vincolo di prezzo ({filtro_desc}). "
                            "Possiamo provare ad ampliare la fascia di budget o esplorare una famiglia olfattiva differente."
                        )
                    else:
                        fallback_reply = (
                            "Non ho trovato a catalogo una fragranza che corrisponda a queste specifiche caratteristiche. "
                            "Puoi provare a indicare una nota più generica oppure iniziare il nostro percorso guidato."
                        )
                    self.sessions[session_id].append({"role": "user", "content": user_query})
                    self.sessions[session_id].append({"role": "assistant", "content": fallback_reply})
                    return {"reply": fallback_reply, "options": ["🎯 Guidami nella scelta"], "products": [], "step": None, "mode": "free"}

                context_str = "\n\n".join(candidates_text)

                if is_seeking_similar_alternative and active:
                    active_info = (
                        f"[FRAGRANZA ATTUALE DI PARTENZA: '{active['name']}' ({active.get('brand', 'Profumeria Artistica')})]\n"
                        f"- Famiglia: {active.get('family', '')} | Prezzo attuale: {active.get('price', '')} EUR\n"
                        f"- Note e profilo: {active.get('document', '')[:200]}\n\n"
                    )
                    system_prompt = (
                        "Sei un Maitre Parfumeur raffinato ed esperto di una boutique di profumeria artistica.\n\n"
                        "COMPITO DI SELEZIONE ALTERNATIVA:\n"
                        f"Il cliente sta chiedendo un'ALTERNATIVA al profumo che stava valutando: '{active['name']}' ({active.get('family', '')}).\n"
                        "Hai a disposizione una lista di CANDIDATI dal catalogo che rispettano già i vincoli di budget e affinità olfattiva.\n"
                        "1. Analizza la richiesta dell'utente.\n"
                        f"2. Scegli TRA I CANDIDATI il profumo più affine e coerente per famiglia ({active.get('family', '')}), accordi olfattivi e carattere, che rispetti la fascia economica richiesta.\n"
                        f"3. Nella tua spiegazione (massimo 2-3 frasi), spiega con garbo ed eleganza perché questa creazione è l'alternativa ideale a '{active['name']}', evidenziando cosa condividono (note o sensazione) e cosa la distingue nella fascia desiderata.\n"
                        "4. FORMATO RISPOSTA:\n"
                        "   [ID: PRODOTTO_X]\n"
                        "   Spiegazione raffinata ed esperta (massimo 2-3 frasi) del perché è l'alternativa ideale.\n"
                        "   NON inserire link, prezzi o immagini nel testo.\n"
                        "5. SCARTO: Se NESSUN candidato è adatto, scrivi '[ID: NESSUNO]' all'inizio."
                    )
                    user_message_content = f"{active_info}RICHIESTA UTENTE: {user_query}\n\nCANDIDATI ALTERNATIVI DISPONIBILI:\n{context_str}"
                else:
                    system_prompt = (
                        "Sei un Maitre Parfumeur raffinato ed esperto di una boutique di profumeria artistica.\n\n"
                        "COMPITO DI SELEZIONE RIGOROSA:\n"
                        "Hai a disposizione una lista di CANDIDATI estratti dal catalogo che rispettano già i vincoli di budget e note richiesti.\n"
                        "1. Analizza la richiesta dell'utente.\n"
                        "2. Scegli TRA I CANDIDATI ESATTAMENTE UN SOLO PRODOTTO che rispecchia REALMENTE e COERENTEMENTE la richiesta.\n"
                        "3. Se l'utente ha chiesto una nota specifica o una stagione, dai priorità alla fragranza che la contiene ed evidenzia con eleganza la sua armonia.\n"
                        "4. REGOLA ANTI-CONTRADDIZIONE: Se un candidato è caldo/intenso, NON proporlo per richieste di freschezza marina o leggerezza.\n"
                        "5. FORMATO RISPOSTA:\n"
                        "   [ID: PRODOTTO_X]\n"
                        "   Descrizione raffinata ed esperta (massimo 2-3 frasi) del perché questa creazione è la scelta perfetta per le sue note olfattive ed occasioni d'uso.\n"
                        "   NON inserire link, prezzi o immagini nel testo.\n"
                        "6. SCARTO: Se NESSUN candidato è adatto, scrivi '[ID: NESSUNO]' all'inizio e spiega gentilmente che al momento non abbiamo la fragranza adatta."
                    )
                    user_message_content = f"RICHIESTA UTENTE: {user_query}\n\nCANDIDATI CATALOGO DISPONIBILI:\n{context_str}"

                messages = [{"role": "system", "content": system_prompt}]
                messages.append({"role": "user", "content": user_message_content})

                response = self.client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=messages,
                    temperature=0.0
                )
                reply = response.choices[0].message.content

                selected_product = None
                match = re.search(r"\[ID:\s*(PRODOTTO_\d+|NESSUNO)\]", reply, re.IGNORECASE)
                if match:
                    selected_id = match.group(1).upper()
                    if selected_id in candidates_map:
                        selected_product = candidates_map[selected_id]
                        self.active_perfumes[session_id] = selected_product
                        print(f"[ADVISOR] Profumo attivo registrato: {candidates_map[selected_id]['name']}")
                    reply = re.sub(r"\[ID:\s*(PRODOTTO_\d+|NESSUNO)\]\s*", "", reply).strip()
                else:
                    selected_product = candidates_map["PRODOTTO_1"]
                    self.active_perfumes[session_id] = selected_product
                    print(f"[ADVISOR FALLBACK] Profumo attivo registrato (primo candidato): {candidates_map['PRODOTTO_1']['name']}")

                product_payload = []
                if selected_product:
                    enriched = self._enrich_product_payload(selected_product, card_type="standard")
                    product_payload.append(enriched)

                self.sessions[session_id].append({"role": "user", "content": user_query})
                self.sessions[session_id].append({"role": "assistant", "content": reply})

                return {"reply": reply, "options": [], "products": product_payload, "step": None, "mode": "free"}