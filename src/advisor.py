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

GUIDED_STEPS = {
    1: {
        "question": "Che tipo di sensazione o famiglia olfattiva preferisci?",
        "options": ["Fresco & Agrumato", "Dolce & Gourmand", "Ambrato & Orientale", "Legnoso & Cuoiato"]
    },
    2: {
        "question": "In quale contesto o stagione desideri indossarlo principalmente?",
        "options": ["Tutti i giorni / Ufficio", "Serata speciale o elegante", "Primavera / Estate", "Autunno / Inverno"]
    },
    3: {
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
        # session_id -> {"step": None|1|2|3, "answers": []}
        self.guided_states = defaultdict(lambda: {"step": None, "answers": []})

        self.catalog_products = []
        if CATALOG_PATH.exists():
            try:
                with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                    self.catalog_products = json.load(f)
            except Exception as e:
                print(f"[ADVISOR] Avviso: caricamento catalog.json fallito: {e}")

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

    def _extract_price_constraints(self, query: str, active_perfume: dict | None) -> tuple[float | None, float | None, str]:
        """
        Estrae vincoli di budget (min e max) sia relativi (es. 'più economico' del profumo attivo)
        sia assoluti (es. 'sotto i 200€', 'tra 100 e 150 euro').
        Restituisce (min_price, max_price, query_pulita_per_ricerca).
        """
        min_p = None
        max_p = None
        q = query.strip()

        # 1. VINCOLI RELATIVI (rispetto al profumo attivo)
        is_cheaper = bool(re.search(r"\b(pi[uù]\s+economic[oa]|meno\s+costos[oa]|pi[uù]\s+abbordabile|pi[uù]\s+accessibile|spendere\s+meno|a\s+meno|costa\s+meno)\b", q, re.I))
        is_expensive = bool(re.search(r"\b(pi[uù]\s+costos[oa]|pi[uù]\s+pregiat[oa]|di\s+fascia\s+pi[uù]\s+alta|pi[uù]\s+esclusiv[oa]|di\s+lusso|alta\s+gamma|alta\s+profumeria|spendere\s+di\s+pi[uù])\b", q, re.I))

        if is_cheaper and active_perfume and active_perfume.get("price"):
            current_price = float(active_perfume["price"])
            max_p = max(0.0, current_price - 0.5)
            print(f"[PRICE PARSER] Riconosciuta richiesta 'più economico': max_price impostato a {max_p}€ (precedente: {current_price}€)")

        elif is_expensive and active_perfume and active_perfume.get("price"):
            current_price = float(active_perfume["price"])
            min_p = current_price + 0.5
            print(f"[PRICE PARSER] Riconosciuta richiesta 'più esclusivo/costoso': min_price impostato a {min_p}€ (precedente: {current_price}€)")

        # 2. VINCOLI ASSOLUTI (Pattern numerici espliciti)
        # 2a. Range esplicito: 'tra 100 e 200 euro', 'da 80 a 120€'
        range_match = re.search(r"\b(?:tra|da)\s+(?:i\s+)?(\d+(?:[.,]\d+)?)\s*(?:€|euro)?\s+(?:e|a)\s+(?:i\s+)?(\d+(?:[.,]\d+)?)\s*(?:€|euro)?\b", q, re.I)
        if range_match:
            min_p = float(range_match.group(1).replace(",", "."))
            max_p = float(range_match.group(2).replace(",", "."))
            print(f"[PRICE PARSER] Range rilevato: da {min_p}€ a {max_p}€")

        # 2b. Tetto massimo: 'sotto i 200€', 'meno di 150 euro', 'massimo 120', 'budget 100€', 'entro 180'
        max_match = re.search(r"\b(?:sotto\s+(?:i\s+)?|meno\s+di\s+|massimo\s+|max\s+|entro\s+(?:i\s+)?|fino\s+a\s+|budget\s+(?:di\s+)?|<|<=)\s*(\d+(?:[.,]\d+)?)\s*(?:€|euro)?\b", q, re.I)
        if max_match and not range_match:
            val = float(max_match.group(1).replace(",", "."))
            max_p = val if max_p is None else min(max_p, val)
            print(f"[PRICE PARSER] Limite massimo rilevato: {max_p}€")

        # 2c. Soglia minima: 'oltre i 200€', 'più di 150 euro', 'almeno 100', 'minimo 80'
        min_match = re.search(r"\b(?:sopra\s+(?:i\s+)?|oltre\s+(?:i\s+)?|pi[uù]\s+di\s+|almeno\s+|minimo\s+|min\s+|>|>=)\s*(\d+(?:[.,]\d+)?)\s*(?:€|euro)?\b", q, re.I)
        if min_match and not range_match:
            val = float(min_match.group(1).replace(",", "."))
            min_p = val if min_p is None else max(min_p, val)
            print(f"[PRICE PARSER] Limite minimo rilevato: {min_p}€")

        # 3. PULIZIA DELLA QUERY PER LA RICERCA SEMANTICA
        # Rimuove le formule di prezzo dalla stringa per non sporcare il calcolo vettoriale di ChromaDB
        search_query = q
        search_query = re.sub(r"\b(?:tra|da)\s+(?:i\s+)?\d+(?:[.,]\d+)?\s*(?:€|euro)?\s+(?:e|a)\s+(?:i\s+)?\d+(?:[.,]\d+)?\s*(?:€|euro)?\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b(?:sotto\s+(?:i\s+)?|meno\s+di\s+|massimo\s+|max\s+|entro\s+(?:i\s+)?|fino\s+a\s+|budget\s+(?:di\s+)?|<|<=)\s*\d+(?:[.,]\d+)?\s*(?:€|euro)?\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b(?:sopra\s+(?:i\s+)?|oltre\s+(?:i\s+)?|pi[uù]\s+di\s+|almeno\s+|minimo\s+|min\s+|>|>=)\s*\d+(?:[.,]\d+)?\s*(?:€|euro)?\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b\d+\s*(?:€|euro)\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b(pi[uù]\s+economic[oa]|meno\s+costos[oa]|pi[uù]\s+abbordabile|pi[uù]\s+accessibile|spendere\s+meno|a\s+meno)\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\b(pi[uù]\s+costos[oa]|pi[uù]\s+pregiat[oa]|di\s+fascia\s+pi[uù]\s+alta|pi[uù]\s+esclusiv[oa]|di\s+lusso|alta\s+gamma|alta\s+profumeria|spendere\s+di\s+pi[uù])\b", "", search_query, flags=re.I)
        search_query = re.sub(r"\s+", " ", search_query).strip()

        # Se dopo la rimozione dei filtri di prezzo la frase è priva di indicazioni olfattive
        # (es. era solo 'cercami un alternativa più economica'), eredita il contesto del profumo attivo
        words = [w for w in re.findall(r"\b[a-zA-Zàèéìòù]+\b", search_query.lower()) if len(w) > 2 and w not in ["vorrei", "cerco", "cercami", "trova", "trovami", "consiglia", "consigliami", "profumo", "fragranza", "alternativa", "altro", "altra"]]
        if not words and active_perfume:
            fam = active_perfume.get("family", "")
            search_query = f"Profumo {fam} affine a {active_perfume['name']}"
            print(f"[PRICE PARSER] Nessuna nota specificata: la ricerca eredita la famiglia '{fam}' del profumo attivo.")

        return min_p, max_p, search_query

    def _determine_intent(self, query: str, active_perfume: dict) -> str:
        if not active_perfume:
            return "CAMBIA"

        q = re.sub(r"[?!.,;:]", " ", query.lower()).strip()

        # 1. CAMBIO ESPLICITO, RICERCA O RICHIESTA DI BUDGET DIVERSO
        switch_patterns = [
            # Formule di prezzo relativo (es. 'più economico', 'meno costoso') -> CAMBIA sempre
            r"\b(pi[uù]\s+economic[oa]|meno\s+costos[oa]|pi[uù]\s+abbordabile|pi[uù]\s+accessibile|spendere\s+meno|a\s+meno|costa\s+meno)\b",
            r"\b(pi[uù]\s+costos[oa]|pi[uù]\s+pregiat[oa]|alta\s+gamma|spendere\s+di\s+pi[uù])\b",

            # Filtri di budget espliciti nella query (es. 'sotto i 200€', 'meno di 150', 'tra 100 e 150')
            r"\b(?:sotto\s+i?|meno\s+di|entro\s+i?|fino\s+a|oltre\s+i?|pi[uù]\s+di|budget\s+di?)\s*\d+\b",
            r"\b(?:tra|da)\s+\d+.*\b(?:e|a)\s+\d+\b",

            # Formule con 'qualcosa' o ricerca
            r"\b(vorrei|voglio|cerco|cercavo|cercami|trova|trovami|proponi|proponimi)\s+qualcosa\b",
            r"\bqualcosa\s+con\b", r"\bqualcosa\s+di\b",
            r"\bqualcos[' ]altro\b", r"\bqualcosa\s+d[' ]altr[oa]\b",

            # Richiesta esplicita di profumo o alternativa
            r"\b(vorrei|voglio|cerco|cercavo|cerca|cercami|trova|trovami|consiglia|consigliami|mostra|mostrami|proponi|proponimi|suggerisci|suggeriscimi)\b.*\b(un|una|uno|profumo|fragranza|note|accordo|flacone|alternativa)\b",
            r"\bun\s+altr[oa]\b", r"\bun[' ]altra\b",
            r"\baltr[oaei]\s+profum[ie]\b", r"\baltr[oaei]\s+fragranz[ea]\b",
            r"\b(mostra|mostrami|consiglia|consigliami|trova|trovami|cerca|cercami|proponi|proponimi)\s+altr[oa]\b",
            r"\bcambia\s+profumo\b", r"\bcambiamo\b", r"\bpassiamo\s+a\b",
            r"\balternativa\b", r"\balternative\b", r"\bdivers[oaei]\b"
        ]
        if any(re.search(p, q) for p in switch_patterns):
            return "CAMBIA"

        # 2. VALUTAZIONE DETERMINISTICA SUL PROFUMO ATTIVO
        stay_patterns = [
            r"\b(le|quali|che|su[oaei])\s+note\b",
            r"\bnote\s+di\s+(testa|cuore|fondo)\b",
            r"\b(ha|contiene)\s+note\b",
            r"\bpiramide\b", r"\bcomposizione\b",
            r"\b(quali|che)\s+ingredienti\b",
            r"\bsu[oaei]\b",
            r"\bquest[oaei]\b",
            r"\blo\s+posso\b", r"\bla\s+posso\b", r"\bsi\s+pu[oò]\b",

            # Domande sul costo/prezzo del prodotto corrente
            r"\b(quanto\s+costa|qual\s+[eè]\s+il\s+prezzo|quanto\s+viene|costo\s+effettivo|[eè]\s+costos[oa])\b",
            r"^\s*(prezzo|costo)\s*\??\s*$",

            # Performance e occasioni
            r"\b(quanto\s+dura|durata|persistenza|proiezione|sillage|scia)\b",
            r"\b(va\s+bene|è\s+adatt[oa]|adatt[oa]\s+a)\b",
            r"\b(per\s+l'ufficio|in\s+ufficio|al\s+lavoro)\b",
            r"\b(di\s+giorno|di\s+sera|a\s+cena|a\s+pranzo)\b",
            r"\b(in\s+spiaggia|al\s+mare|in\s+palestra)\b",
            r"\b(estiv[oae]|invernal[ei]|primaveril[ei]|autunnal[ei])\b"
        ]
        if any(re.search(p, q) for p in stay_patterns):
            return "VALUTA"

        # 3. FALLBACK LLM
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
                "reply": "Perfetto! Ripartiamo con 3 brevi domande per selezionare le fragranze ideali per te.\n\n" + GUIDED_STEPS[1]["question"],
                "options": GUIDED_STEPS[1]["options"],
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
                    "step": 2,
                    "mode": "guided"
                }
            elif effective_step == 2:
                first_ans = state["answers"][0] if len(state["answers"]) > 0 else "Artistico"
                state["answers"] = [first_ans, query_clean]
                state["step"] = 3
                return {
                    "reply": GUIDED_STEPS[3]["question"],
                    "options": GUIDED_STEPS[3]["options"],
                    "step": 3,
                    "mode": "guided"
                }
            elif effective_step == 3:
                first_ans = state["answers"][0] if len(state["answers"]) > 0 else "Artistico"
                second_ans = state["answers"][1] if len(state["answers"]) > 1 else "Tutti i giorni"
                state["answers"] = [first_ans, second_ans, query_clean]
                state["step"] = None
                return self._generate_guided_recommendations(state["answers"], session_id)

        return self._handle_free_chat(user_query, session_id, max_price)

    def _generate_guided_recommendations(self, answers: list, session_id: str) -> dict:
        family = answers[0] if len(answers) > 0 else "Artistico"
        occasion = answers[1] if len(answers) > 1 else "Tutti i giorni"
        budget_str = answers[2] if len(answers) > 2 else "Nessun limite"

        min_p = None
        max_p = None

        if "sotto 120" in budget_str.lower() or "< 120" in budget_str:
            max_p = 120.0
        elif "120" in budget_str and "200" in budget_str:
            min_p = 120.0
            max_p = 200.0
        elif "oltre 200" in budget_str.lower() or "> 200" in budget_str:
            min_p = 200.0

        search_prompt = f"Profumo {family} ideale per {occasion}."

        results = self.search_engine.search(
            query=search_prompt,
            min_price=min_p,
            max_price=max_p,
            n_results=3
        )

        context_items = []
        first_product = None

        if results["ids"] and len(results["ids"][0]) > 0:
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i]
                doc = results["documents"][0][i]

                prod_data = {
                    "name": meta.get("name", ""),
                    "brand": meta.get("brand", "Profumeria Artistica"),
                    "price": meta.get("price", 0.0),
                    "family": meta.get("family", ""),
                    "ptype": meta.get("ptype", ""),
                    "add_to_cart_url": meta.get("add_to_cart_url", ""),
                    "product_page_url": meta.get("product_page_url", ""),
                    "image_url": meta.get("image_url", ""),
                    "document": doc
                }

                if i == 0:
                    first_product = prod_data

                context_items.append(
                    f"PROPOSTA {i+1}:\n"
                    f"- Nome: {prod_data['name']} ({prod_data['brand']})\n"
                    f"  Tipologia: {prod_data['ptype']} | Famiglia: {prod_data['family']}\n"
                    f"  Prezzo di vendita: {prod_data['price']} EUR\n"
                    f"  Link Acquisto: {prod_data['add_to_cart_url']}\n"
                    f"  Profilo olfattivo e d'uso: {doc}"
                )

        if not context_items:
            return {
                "reply": "Non ho trovato fragranze a catalogo che rientrino esattamente in questa specifica combinazione di note e fascia di prezzo. Prova a selezionare un'altra fascia o una famiglia olfattiva differente!",
                "options": ["🎯 Ricomincia percorso guidato", "💬 Fai una domanda libera"],
                "step": None,
                "mode": "free"
            }

        if first_product:
            self.active_perfumes[session_id] = first_product

        context_str = "\n\n".join(context_items)

        prompt = (
            f"L'utente ha completato il percorso guidato con queste preferenze:\n"
            f"- Famiglia olfattiva: {family}\n"
            f"- Occasione/Uso: {occasion}\n"
            f"- Fascia Budget: {budget_str}\n\n"
            f"PRODOTTI REALI PRESENTI A CATALOGO:\n{context_str}\n\n"
            "REGOLE ANTI-ALLUCINAZIONE E STRUTTURA DELLA RISPOSTA:\n"
            "1. Presenta ESCLUSIVAMENTE i prodotti elencati sopra. NON inventare nomi, marchi, prezzi o profumi non presenti nel testo.\n"
            "2. Per ciascun profumo adotta TASSATIVAMENTE questa struttura ordinata su righe separate:\n"
            "   - **Nome Profumo** di Brand\n"
            "   - Breve descrizione raffinata (1 o 2 frasi) con le note salienti e il motivo per cui rispecchia la richiesta.\n"
            "   - **Prezzo:** PREZZO_DI_VENDITA EUR\n"
            "   - [Aggiungi al Carrello](URL_FORNITO)\n\n"
            "3. Il prezzo DEVE apparire sulla riga successiva alla descrizione e PRIMA del link al carrello.\n"
            "Sii raffinato, sintetico ed elegante."
        )

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        reply = response.choices[0].message.content

        self.sessions[session_id].append({"role": "user", "content": f"Percorso guidato completato: {', '.join(answers)}"})
        self.sessions[session_id].append({"role": "assistant", "content": reply})

        return {
            "reply": reply,
            "options": ["🎯 Ricomincia percorso guidato", "💬 Fai una domanda libera"],
            "step": None,
            "mode": "free"
        }

    def _handle_free_chat(self, user_query: str, session_id: str, max_price: float) -> dict:
        history = self.sessions[session_id]
        active_before = self.active_perfumes.get(session_id)

        # 1. Riconoscimento nominale esplicito di un profumo citato a catalogo
        mentioned_product = self._find_mentioned_product(user_query)
        is_new_product_switch = False

        if mentioned_product:
            if not active_before or active_before.get("name") != mentioned_product.get("name"):
                is_new_product_switch = True
            self.active_perfumes[session_id] = mentioned_product
            print(f"[ENTITY MATCH] '{mentioned_product['name']}' (Nuovo switch: {is_new_product_switch})")

        # RAMO 1: Profumo citato esplicitamente per la prima volta -> PREZZO e CARRELLO obbligatori
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
                "2. Trattandosi della prima presentazione di questa fragranza, includi OBBLIGATORIAMENTE nelle ultime due righe:\n"
                "   **Prezzo:** PREZZO_DI_VENDITA EUR\n"
                "   [Aggiungi al Carrello](URL_FORNITO)\n"
                "3. FORMATO RISPOSTA OBBLIGATORIO:\n"
                "   **Nome Profumo** di Brand\n"
                "   Descrizione raffinata e risposta puntuale alla richiesta del cliente (massimo 2-3 frasi).\n"
                "   **Prezzo:** PREZZO EUR\n"
                "   [Aggiungi al Carrello](URL_FORNITO)"
            )

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history[-2:])
            messages.append({"role": "user", "content": f"RICHIESTA UTENTE: {user_query}\n\nCONTESTO:\n{context_str}"})

        else:
            active = self.active_perfumes.get(session_id)
            intent = self._determine_intent(user_query, active)
            is_follow_up = (intent == "VALUTA" and active is not None)

            print(f"\n[ROUTER DEBUG] Profumo attivo: '{active.get('name') if active else 'NESSUNO'}'")
            print(f"[ROUTER DEBUG] Domanda: '{user_query}' -> Decisione: {'SEGUI PRODOTTO (VALUTA)' if is_follow_up else 'CERCA NUOVO (CAMBIA)'}")

            # RAMO 2: Domanda di chiarimento/valutazione sullo stesso profumo attivo -> SENZA CARRELLO
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
                    "4. GESTIONE DI PREZZO E LINK AL CARRELLO:\n"
                    "   - Nelle normali domande di chiarimento, note, parere o idoneità, NON inserire né il prezzo né il link al carrello.\n"
                    "   - Inserisci il prezzo e il link SOLO se l'utente richiede ESPLICITAMENTE il costo, il prezzo o il link di acquisto.\n"
                    "5. SINTESI TOTALE: Massimo 3 o 4 frasi concise. Niente testi dispersivi."
                )

                messages = [{"role": "system", "content": system_prompt}]
                messages.extend(history[-2:])
                messages.append({"role": "user", "content": f"RICHIESTA UTENTE: {user_query}\n\nCONTESTO:\n{context_str}"})

            # RAMO 3: Ricerca di un nuovo profumo (con estrazione dinamica dei vincoli di prezzo)
            else:
                parsed_min_p, parsed_max_p, search_query_clean = self._extract_price_constraints(user_query, active)

                # Priorità ai vincoli estratti dal testo; fallback su max_price passato come parametro
                effective_max_p = parsed_max_p if parsed_max_p is not None else max_price
                effective_min_p = parsed_min_p

                print(f"[SEARCH EXEC] Query per ChromaDB: '{search_query_clean}' | Filtri Prezzo: min={effective_min_p}, max={effective_max_p}")

                results = self.search_engine.search(
                    query=search_query_clean,
                    min_price=effective_min_p,
                    max_price=effective_max_p,
                    n_results=5
                )

                if not results["ids"] or len(results["ids"][0]) == 0:
                    if effective_max_p or effective_min_p:
                        filtro_desc = f"sotto i {effective_max_p}€" if effective_max_p else f"sopra i {effective_min_p}€"
                        fallback_reply = (
                            f"Non ho trovato a catalogo una fragranza che corrisponda a queste caratteristiche nella fascia di prezzo indicata ({filtro_desc}). "
                            "Puoi provare ad ampliare il budget o richiedere una famiglia olfattiva differente."
                        )
                    else:
                        fallback_reply = (
                            "Non ho trovato a catalogo una fragranza che corrisponda a queste specifiche caratteristiche. "
                            "Puoi provare a indicare una famiglia olfattiva più generica oppure iniziare il nostro percorso guidato."
                        )
                    self.sessions[session_id].append({"role": "user", "content": user_query})
                    self.sessions[session_id].append({"role": "assistant", "content": fallback_reply})
                    return {"reply": fallback_reply, "options": ["🎯 Guidami nella scelta"], "step": None, "mode": "free"}

                candidates_text = []
                candidates_map = {}
                for i in range(len(results["ids"][0])):
                    meta = results["metadatas"][0][i]
                    doc = results["documents"][0][i]
                    pid = f"PRODOTTO_{i+1}"
                    candidates_map[pid] = {
                        "name": meta.get("name", ""),
                        "brand": meta.get("brand", "Profumeria Artistica"),
                        "price": meta.get("price", 0.0),
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
                        f"Link Acquisto: {meta['add_to_cart_url']}\n"
                        f"Descrizione e Note: {doc}"
                    )

                context_str = "\n\n".join(candidates_text)

                system_prompt = (
                    "Sei un Maitre Parfumeur raffinato ed esperto di una boutique di profumeria artistica.\n\n"
                    "COMPITO DI SELEZIONE RIGOROSA:\n"
                    "Hai a disposizione una lista di CANDIDATI estratti dal catalogo che rispettano già i vincoli di budget e note richiesti.\n"
                    "1. Analizza la richiesta dell'utente.\n"
                    "2. Scegli TRA I CANDIDATI ESATTAMENTE UN SOLO PRODOTTO che rispecchia REALMENTE e COERENTEMENTE la richiesta.\n"
                    "3. Se l'utente ha chiesto un'alternativa più economica o ha specificato un tetto di spesa, evidenzia con eleganza come questa creazione offra grande caratura mantenendosi nella fascia desiderata.\n"
                    "4. REGOLA ANTI-CONTRADDIZIONE: Se un candidato è caldo/intenso, NON proporlo per richieste di freschezza marina o leggerezza.\n"
                    "5. FORMATO RISPOSTA OBBLIGATORIO:\n"
                    "   [ID: PRODOTTO_X]\n"
                    "   **Nome Profumo** di Brand\n"
                    "   Descrizione raffinata e diretta (massimo 2-3 frasi) del perché è la scelta ideale per le sue note olfattive ed occasioni d'uso.\n"
                    "   **Prezzo:** PREZZO EUR\n"
                    "   [Aggiungi al Carrello](URL_FORNITO)\n\n"
                    "   NOTA: Riporta TASSATIVAMENTE il prezzo sulla riga successiva alla descrizione e IMMEDIATAMENTE PRIMA del link al carrello.\n"
                    "6. SCARTO: Se NESSUN candidato è adatto, scrivi '[ID: NESSUNO]' all'inizio e spiega gentilmente che al momento non abbiamo la fragranza adatta."
                )

                messages = [{"role": "system", "content": system_prompt}]
                messages.append({"role": "user", "content": f"RICHIESTA UTENTE: {user_query}\n\nCANDIDATI CATALOGO DISPONIBILI:\n{context_str}"})

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=0.0
        )
        reply = response.choices[0].message.content

        # Registrazione del profumo attivo per il Ramo 3 (da ricerca candidati)
        if not (is_new_product_switch and mentioned_product) and not is_follow_up and "candidates_map" in locals():
            match = re.search(r"\[ID:\s*(PRODOTTO_\d+|NESSUNO)\]", reply, re.IGNORECASE)
            if match:
                selected_id = match.group(1).upper()
                if selected_id in candidates_map:
                    self.active_perfumes[session_id] = candidates_map[selected_id]
                    print(f"[ADVISOR] Profumo attivo registrato: {candidates_map[selected_id]['name']}")
                reply = re.sub(r"\[ID:\s*(PRODOTTO_\d+|NESSUNO)\]\s*", "", reply).strip()
            else:
                self.active_perfumes[session_id] = candidates_map["PRODOTTO_1"]
                print(f"[ADVISOR FALLBACK] Profumo attivo registrato (primo candidato): {candidates_map['PRODOTTO_1']['name']}")

        self.sessions[session_id].append({"role": "user", "content": user_query})
        self.sessions[session_id].append({"role": "assistant", "content": reply})

        return {"reply": reply, "options": [], "step": None, "mode": "free"}