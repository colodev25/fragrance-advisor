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
        if CATALOG_PATH.exists():
            try:
                with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                    self.catalog_products = json.load(f)
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
        scent_terms = [
            "agrumat", "fresc", "acquat", "marin", "aromat", "verd",
            "floreal", "fior", "fruttat", "talcat",
            "dolc", "cald", "gourmand", "vanigli", "ambrat", "oriental",
            "legnos", "intens", "speziat", "cuoi", "chypre", "tabacc", "muschi",
            "vaniglia", "oud", "legno", "rosa", "iris", "gelsomino", "ambra",
            "bergamotto", "limone", "arancia", "cedro", "sandalo", "vetiver",
            "patchouli", "tonka", "pepe", "cannella", "incenso", "cacao",
            "caffe", "mandorla", "fico", "sale", "mirra", "lavanda", "neroli",
            "tuberosa", "pesca", "mela", "pompelmo"
        ]
        q_lower = query.lower()
        return any(term in q_lower for term in scent_terms)

    def _enrich_product_payload(self, prod_dict: dict, card_type: str = "slideover") -> dict:
        """
        Estrae gli attributi per la Product Card:
        - product_page_url: link diretto per la navigazione
        - story: descrizione completa senza tagli '...'
        - key_notes: accordi salienti per le pills
        - traits: riga compatta di metadati
        """
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

            trait_parts = [p_ptype]
            tags = [t.lower() for t in cat_match.get("tags", [])]
            if "unisex" in tags:
                trait_parts.append("Unisex")
            elif any("lei" in t or "donna" in t for t in tags):
                trait_parts.append("Per Lei")
            elif any("lui" in t or "uomo" in t for t in tags):
                trait_parts.append("Per Lui")
            else:
                trait_parts.append("Unisex")

            if any("invern" in t for t in tags):
                trait_parts.append("Autunno / Inverno")
            elif any("estiv" in t or "estate" in t for t in tags):
                trait_parts.append("Primavera / Estate")
            else:
                trait_parts.append("Scia persistente")

            traits = " • ".join(trait_parts)

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
                u_prof = cat_match.get("usage_profile", "").strip()
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
            traits = f"{p_ptype} • {p_family or 'Profumeria Artistica'}"

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
            print(f"[PRICE PARSER] 'più economico': max_price impostato a {max_p}€ (precedente: {current_price}€)")

        elif is_expensive and active_perfume and active_perfume.get("price"):
            current_price = float(active_perfume["price"])
            min_p = current_price + 0.5
            print(f"[PRICE PARSER] 'più costoso': min_price impostato a {min_p}€ (precedente: {current_price}€)")

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
            n_results=3
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

                if i == 0:
                    first_product = prod_data

                enriched = self._enrich_product_payload(prod_data, card_type="slideover")
                structured_products.append(enriched)

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

            # RAMO 2: Chiarimento o approfondimento sullo stesso profumo attivo -> RISPOSTA TESTUALE PURA
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

            # RAMO 3: Ricerca di un nuovo profumo su ChromaDB con mantenimento del contesto "Alternativa"
            else:
                parsed_min_p, parsed_max_p, search_query_clean = self._extract_price_constraints(user_query, active)

                effective_max_p = parsed_max_p if parsed_max_p is not None else max_price
                effective_min_p = parsed_min_p

                # LOGICA DI PRESERVAZIONE ALTERNATIVA:
                # Se c'è un profumo attivo e l'utente NON ha specificato una famiglia o note opposte/nuove,
                # cerca fragranze affini per famiglia e accordi al profumo attivo
                is_seeking_similar_alternative = (active is not None and not self._has_explicit_olfactory_redirect(search_query_clean))

                if is_seeking_similar_alternative and active:
                    active_fam = active.get("family", "")
                    cat_match = next((cp for cp in self.catalog_products if cp.get("name", "").strip().lower() == active.get("name", "").strip().lower()), None)
                    key_notes_list = []
                    if cat_match:
                        pyr = cat_match.get("olfactory_pyramid", {})
                        key_notes_list = pyr.get("top", []) + pyr.get("heart", []) + pyr.get("base", [])

                    notes_str = ", ".join(key_notes_list[:5]) if key_notes_list else active_fam
                    chroma_query = f"Profumo {active_fam}. Note olfattive: {notes_str}. {active.get('document', '')[:120]}"

                    print(f"[ALTERNATIVE SEARCH] Ricerca alternativa affine a '{active['name']}' ({active_fam}) | Note: {notes_str} | Filtri Prezzo: min={effective_min_p}, max={effective_max_p}")
                else:
                    chroma_query = search_query_clean
                    print(f"[SEARCH EXEC] Query ChromaDB: '{search_query_clean}' | Filtri Prezzo: min={effective_min_p}, max={effective_max_p}")

                results = self.search_engine.search(
                    query=chroma_query,
                    min_price=effective_min_p,
                    max_price=effective_max_p,
                    n_results=8
                )

                candidates_text = []
                candidates_map = {}
                candidate_idx = 1

                if results["ids"] and len(results["ids"][0]) > 0:
                    for i in range(len(results["ids"][0])):
                        meta = results["metadatas"][0][i]
                        doc = results["documents"][0][i]

                        # Se stiamo cercando un'alternativa all'attivo, escludiamo l'attivo stesso
                        if is_seeking_similar_alternative and active and meta.get("name", "").strip().lower() == active.get("name", "").strip().lower():
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
                            f"Non ho trovato a catalogo un'alternativa affine che rispetti questo vincolo di prezzo ({filtro_desc}). "
                            "Possiamo provare ad ampliare la fascia di budget o esplorare una famiglia olfattiva differente."
                        )
                    else:
                        fallback_reply = (
                            "Non ho trovato a catalogo una fragranza che corrisponda a queste specifiche caratteristiche. "
                            "Puoi provare a indicare una famiglia olfattiva più generica oppure iniziare il nostro percorso guidato."
                        )
                    self.sessions[session_id].append({"role": "user", "content": user_query})
                    self.sessions[session_id].append({"role": "assistant", "content": fallback_reply})
                    return {"reply": fallback_reply, "options": ["🎯 Guidami nella scelta"], "products": [], "step": None, "mode": "free"}

                context_str = "\n\n".join(candidates_text)

                # Prompt personalizzato per proporre una VERA ALTERNATIVA affine
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
                        "3. Se l'utente ha specificato un budget o una preferenza economica, evidenzia con eleganza come questa creazione offra grande caratura nella fascia desiderata.\n"
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
                        print(f"[ADVISOR] Nuovo profumo attivo registrato: {candidates_map[selected_id]['name']}")
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