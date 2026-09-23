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

        # Caricamento del catalogo per il matching nominale delle fragranze citate
        self.catalog_products = []
        if CATALOG_PATH.exists():
            try:
                with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                    self.catalog_products = json.load(f)
            except Exception as e:
                print(f"[ADVISOR] Avviso: caricamento catalog.json fallito: {e}")

    def _find_mentioned_product(self, query: str) -> dict | None:
        """
        Individua se nella frase dell'utente è presente il nome di un profumo a catalogo.
        """
        if not self.catalog_products:
            return None

        q_clean = " " + re.sub(r"[?!.,;:\"\'\(\)]", " ", query.lower()) + " "

        for prod in self.catalog_products:
            raw_name = prod.get("name", "").strip()
            if not raw_name:
                continue

            # Rimuove diciture accessorie come formati e concentrazioni per matching robusto
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

    def _determine_intent(self, query: str, active_perfume: dict) -> str:
        if not active_perfume:
            return "CAMBIA"

        q = re.sub(r"[?!.,;:]", " ", query.lower()).strip()

        # 1. CAMBIO ESPLICITO E INTENTI DI RICERCA
        switch_patterns = [
            # Formule con "qualcosa"
            r"\b(vorrei|voglio|cerco|cercavo|cercami|trova|trovami|proponi|proponimi)\s+qualcosa\b",
            r"\bqualcosa\s+con\b", r"\bqualcosa\s+di\b",
            r"\bqualcos[' ]altro\b", r"\bqualcosa\s+d[' ]altr[oa]\b",

            # Verbo di ricerca / richiesta + oggetto (un/una/profumo/note/alternativa...)
            r"\b(vorrei|voglio|cerco|cercavo|cerca|cercami|trova|trovami|consiglia|consigliami|mostra|mostrami|proponi|proponimi|suggerisci|suggeriscimi)\b.*\b(un|una|uno|profumo|fragranza|note|accordo|flacone|alternativa)\b",

            # Richiesta esplicita di alternative ("un altro", "altra fragranza", ecc.)
            r"\bun\s+altr[oa]\b", r"\bun[' ]altra\b",
            r"\baltr[oaei]\s+profum[ie]\b", r"\baltr[oaei]\s+fragranz[ea]\b",
            r"\b(mostra|mostrami|consiglia|consigliami|trova|trovami|cerca|cercami|proponi|proponimi)\s+altr[oa]\b",

            # Reset o cambio esplicito
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
            r"\b(costa|costo|prezzo|euro|€)\b",
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

        # Trigger avvio/riavvio percorso guidato
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

        # Trigger chat libera
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

        # Gestione Step del percorso guidato
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

        # 1. Verifica se l'utente ha citato esplicitamente un profumo a catalogo
        mentioned_product = self._find_mentioned_product(user_query)
        is_new_product_switch = False

        if mentioned_product:
            if not active_before or active_before.get("name") != mentioned_product.get("name"):
                is_new_product_switch = True
            self.active_perfumes[session_id] = mentioned_product
            print(f"[ENTITY MATCH] '{mentioned_product['name']}' (Nuovo switch: {is_new_product_switch})")

        # RAMO 1: L'utente ha citato un NUOVO profumo -> Presentazione con PREZZO e CARRELLO
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
                "1. Rispondi alla richiesta dell'utente con eleganza, autorevolezza e precisione descrivendo la fragranza, "
                "le sue note olfattive o l'aspetto specifico su cui l'utente ha chiesto lumi.\n"
                "2. Trattandosi della prima presentazione di questa fragranza nella conversazione, devi OBBLIGATORIAMENTE includere nelle ultime due righe separate:\n"
                "   **Prezzo:** PREZZO_DI_VENDITA EUR\n"
                "   [Aggiungi al Carrello](URL_FORNITO)\n"
                "3. FORMATO RISPOSTA OBBLIGATORIO:\n"
                "   **Nome Profumo** di Brand\n"
                "   Descrizione raffinata e risposta puntuale alla richiesta del cliente (massimo 2-3 frasi).\n"
                "   **Prezzo:** PREZZO EUR\n"
                "   [Aggiungi al Carrello](URL_FORNITO)\n\n"
                "4. Sii sintetico, elegante e professionale."
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

            # RAMO 2: Follow-up sullo stesso profumo già discusso -> SENZA PREZZO E CARRELLO (salvo richiesta esplicita)
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
                    "   - Se il profumo discusso non va bene per le note o l'occasione richiesta, dillo con chiarezza e aggiungi semplicemente che, se vuole, puoi cercargli una fragranza a catalogo con quelle caratteristiche specifiche.\n"
                    "4. GESTIONE DI PREZZO E LINK AL CARRELLO:\n"
                    "   - Nelle normali domande di chiarimento, note, parere o idoneità, NON inserire né il prezzo né il link al carrello.\n"
                    "   - Inserisci il prezzo e il link SOLO se l'utente richiede ESPLICITAMENTE il costo, il prezzo o il link di acquisto.\n"
                    "5. SINTESI TOTALE: Massimo 3 o 4 frasi concise. Niente testi dispersivi."
                )

                messages = [{"role": "system", "content": system_prompt}]
                messages.extend(history[-2:])
                messages.append({"role": "user", "content": f"RICHIESTA UTENTE: {user_query}\n\nCONTESTO:\n{context_str}"})

            # RAMO 3: Ricerca di un nuovo profumo tramite ChromaDB -> Con PREZZO e CARRELLO
            else:
                results = self.search_engine.search(query=user_query, max_price=max_price, n_results=5)

                if not results["ids"] or len(results["ids"][0]) == 0:
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
                    "Hai a disposizione una lista di CANDIDATI estratti dal catalogo.\n"
                    "1. Analizza la richiesta dell'utente.\n"
                    "2. Scegli TRA I CANDIDATI ESATTAMENTE UN SOLO PRODOTTO che rispecchia REALMENTE e COERENTEMENTE la richiesta.\n"
                    "3. REGOLA ANTI-CONTRADDIZIONE: Se un candidato è caldo/intenso, NON proporlo per richieste di freschezza marina o leggerezza.\n"
                    "4. FORMATO RISPOSTA OBBLIGATORIO (Proposta di un nuovo profumo o alternativa):\n"
                    "   [ID: PRODOTTO_X]\n"
                    "   **Nome Profumo** di Brand\n"
                    "   Descrizione raffinata e diretta (massimo 2-3 frasi) del perché è la scelta ideale per le sue note olfattive ed occasioni d'uso.\n"
                    "   **Prezzo:** PREZZO EUR\n"
                    "   [Aggiungi al Carrello](URL_FORNITO)\n\n"
                    "   NOTA: Riporta TASSATIVAMENTE il prezzo sulla riga successiva alla descrizione e IMMEDIATAMENTE PRIMA del link al carrello.\n"
                    "5. SCARTO: Se NESSUN candidato è adatto, scrivi '[ID: NESSUNO]' all'inizio e spiega gentilmente che al momento non abbiamo la fragranza adatta."
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