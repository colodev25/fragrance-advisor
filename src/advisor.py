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

    def _enrich_product_payload(self, prod_dict: dict, card_type: str = "slideover") -> dict:
        """
        Estrae e organizza gli attributi puliti per il retro della card (Soluzione 2):
        - story: micro-frase d'atmosfera senza ridondanze su nome o brand
        - key_notes: elenco di 4-6 note salienti da mostrare come pillole grafiche
        - traits: stringa compatta di metadati (es. 'Extrait de Parfum • Unisex • Primavera/Estate')
        """
        p_name = prod_dict.get("name", "").strip()
        p_brand = prod_dict.get("brand", "Profumeria Artistica").strip()
        p_price = float(prod_dict.get("price", 0.0))
        p_family = prod_dict.get("family", "").strip()
        p_ptype = prod_dict.get("ptype", "").strip() or "Profumo Artistico"
        p_cart = prod_dict.get("add_to_cart_url", "")
        p_img = prod_dict.get("image_url", "")

        # Cerca il record originale completo da catalog.json
        cat_match = None
        for cp in self.catalog_products:
            if cp.get("name", "").strip().lower() == p_name.lower():
                cat_match = cp
                break

        key_notes = []
        story = ""
        traits = ""

        if cat_match:
            # 1. Estrazione Note Chiave
            pyr = cat_match.get("olfactory_pyramid", {})
            top = [n.strip() for n in pyr.get("top", []) if n.strip()][:2]
            heart = [n.strip() for n in pyr.get("heart", []) if n.strip()][:2]
            base = [n.strip() for n in pyr.get("base", []) if n.strip()][:2]
            key_notes = list(dict.fromkeys(top + heart + base))[:6]

            # Fallback note se piramide assente: estrae dai tag o dalla famiglia
            if not key_notes and cat_match.get("family"):
                key_notes = [f.strip() for f in cat_match["family"].split(",") if f.strip()][:4]

            # 2. Micro-Storytelling depurato
            raw_text = cat_match.get("description", "") or cat_match.get("usage_profile", "")
            # Rimuove l'intestazione standard di catalogazione
            cleaned = re.sub(rf"^Profumo\s+{re.escape(p_name)}.*?\.\s*", "", raw_text, flags=re.I)
            cleaned = re.sub(r"\bformato\s*:\s*[^\.\n]+", "", cleaned, flags=re.I)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()

            # Estrae la prima frase significativa
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', cleaned) if len(s.strip()) > 15]
            if sentences:
                story = sentences[0]
                if len(story) > 150:
                    story = story[:147].rsplit(" ", 1)[0] + "..."
            else:
                fam_label = p_family or "raffinata"
                story = f"Una composizione olfattiva di caratura artistica incentrata su armonie {fam_label.lower()} di grande persistenza."

            # 3. Metadati / Traits
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

        else:
            # Fallback se non presente in catalog.json
            key_notes = [f.strip() for f in p_family.split(",") if f.strip()][:4]
            story = f"Creazione d'alta profumeria che fonde eleganza classica e note olfattive di grande carattere."
            traits = f"{p_ptype} • {p_family or 'Profumeria Artistica'}"

        return {
            "name": p_name,
            "brand": p_brand,
            "price": p_price,
            "family": p_family,
            "ptype": p_ptype,
            "add_to_cart_url": p_cart,
            "image_url": p_img,
            "card_type": card_type,
            "story": story,
            "key_notes": key_notes,
            "traits": traits,
            "description": story
        }

    def _extract_price_constraints(self, query: str, active_perfume: dict | None) -> tuple[float | None, float | None, str]:
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

        words = [w for w in re.findall(r"\b[a-zA-Zàèéìòù]+\b", search_query.lower()) if len(w) > 2 and w not in ["vorrei", "cerco", "cercami", "cercavo", "trova", "trovami", "consiglia", "consigliami", "profumo", "fragranza", "alternativa", "altro", "altra"]]
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

                # Arricchimento secondo la Soluzione 2 (Micro-Storytelling + Note a Pillola)
                enriched = self._enrich_product_payload(prod_data, card_type="slideover")
                structured_products.append(enriched)

                if i == 0:
                    self.active_perfumes[session_id] = prod_data

        if not structured_products:
            return {
                "reply": f"Non ho trovato fragranze a catalogo che rientrino esattamente nella categoria '{macro_label}' per {gender} nella fascia di prezzo selezionata. Prova a scegliere un'altra combinazione!",
                "options": ["🎯 Ricomincia percorso guidato", "💬 Fai una domanda libera"],
                "products": [],
                "step": None,
                "mode": "free"
            }

        # Micro-frase introduttiva d'autore (senza dettagli ridondanti)
        prompt = (
            f"L'utente ha completato il percorso per un profumo {clean_macro} per {gender}, contesto '{occasion}'.\n"
            "Formula ESCLUSIVAMENTE una singola micro-frase introduttiva (massimo 15-20 parole) da Maître Parfumeur "
            "per presentare con garbo ed eleganza la selezione olfattiva.\n"
            "ESEMPIO: 'Ecco le creazioni d'autore selezionate dal nostro archivio per rispecchiare i tuoi desideri:'\n"
            "NON nominare i profumi e NON inserire link o prezzi."
        )

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        reply = response.choices[0].message.content.strip()

        self.sessions[session_id].append({"role": "user", "content": f"Percorso guidato: {macro_label}, {gender}, {occasion}, {budget_str}"})
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

        # RAMO 1: Profumo citato esplicitamente per la prima volta
        if is_new_product_switch and mentioned_product:
            intro_reply = f"Ecco i dettagli della creazione **{mentioned_product['name']}** firmata {mentioned_product.get('brand', 'Profumeria Artistica')}:"

            enriched = self._enrich_product_payload(mentioned_product, card_type="standard")

            self.sessions[session_id].append({"role": "user", "content": user_query})
            self.sessions[session_id].append({"role": "assistant", "content": intro_reply})

            return {"reply": intro_reply, "options": [], "products": [enriched], "step": None, "mode": "free"}

        else:
            active = self.active_perfumes.get(session_id)
            intent = self._determine_intent(user_query, active)
            is_follow_up = (intent == "VALUTA" and active is not None)

            # RAMO 2: Chiarimento sullo stesso profumo -> RISPOSTA TESTUALE PURA
            if is_follow_up:
                context_str = (
                    f"[PRODOTTO ATTUALMENTE DISCUSSO]\n"
                    f"- Nome: {active['name']}\n"
                    f"- Brand: {active.get('brand', 'Profumeria Artistica')}\n"
                    f"- Famiglia: {active.get('family', '')} | Tipologia: {active.get('ptype', '')}\n"
                    f"- Prezzo: {active['price']}€\n"
                    f"- Note e carattere: {active['document']}"
                )

                system_prompt = (
                    "Sei un Maître Parfumeur e critico olfattivo di altissimo livello.\n"
                    "Rispondi al chiarimento dell'utente con autorevolezza ed eleganza in massimo 2 o 3 frasi concise.\n"
                    "Se chiede delle note, descrivi l'evoluzione olfattiva.\n"
                    "NON inserire link o formattazioni di vendita."
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

            # RAMO 3: Nuova ricerca da catalogo -> CARD CLASSICA STANDARD (senza slideover)
            else:
                parsed_min_p, parsed_max_p, search_query_clean = self._extract_price_constraints(user_query, active)

                effective_max_p = parsed_max_p if parsed_max_p is not None else max_price
                effective_min_p = parsed_min_p

                results = self.search_engine.search(
                    query=search_query_clean,
                    min_price=effective_min_p,
                    max_price=effective_max_p,
                    n_results=5
                )

                if not results["ids"] or len(results["ids"][0]) == 0:
                    filtro_desc = f"sotto i {effective_max_p}€" if effective_max_p else f"sopra i {effective_min_p}€" if effective_min_p else ""
                    fallback_reply = (
                        f"Non ho trovato a catalogo una creazione che corrisponda a queste specifiche caratteristiche {filtro_desc}. "
                        "Puoi provare a indicare una nota differente oppure avviare il percorso guidato."
                    )
                    self.sessions[session_id].append({"role": "user", "content": user_query})
                    self.sessions[session_id].append({"role": "assistant", "content": fallback_reply})
                    return {"reply": fallback_reply, "options": ["🎯 Guidami nella scelta"], "products": [], "step": None, "mode": "free"}

                meta = results["metadatas"][0][0]
                doc = results["documents"][0][0]

                selected_product = {
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
                self.active_perfumes[session_id] = selected_product

                enriched = self._enrich_product_payload(selected_product, card_type="standard")
                intro_reply = "In base alla tua richiesta, ho selezionato questa creazione d'autore:"

                self.sessions[session_id].append({"role": "user", "content": user_query})
                self.sessions[session_id].append({"role": "assistant", "content": intro_reply})

                return {"reply": intro_reply, "options": [], "products": [enriched], "step": None, "mode": "free"}