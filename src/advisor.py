import os
import re
from collections import defaultdict
from dotenv import load_dotenv
from openai import OpenAI

try:
    from src.search import FragranceSearchEngine
except ModuleNotFoundError:
    from search import FragranceSearchEngine

load_dotenv()

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

    def _determine_intent(self, query: str, active_perfume: dict) -> str:
        """
        Determina se l'utente vuole continuare a valutare il profumo attivo (VALUTA)
        oppure cercare un nuovo profumo (CAMBIA).
        """
        if not active_perfume:
            return "CAMBIA"

        # Rimuove punteggiatura per facilitare il match deterministico
        q = re.sub(r"[?!.,;:]", " ", query.lower()).strip()

        # 1. CAMBIO ESPLICITO (Priorità assoluta: se l'utente chiede chiaramente un'alternativa)
        switch_patterns = [
            r"\bun altro\b", r"\bun'altra\b", r"\baltri profumi\b", r"\baltre fragranze\b",
            r"\bmostrami altro\b", r"\bconsigliami un altro\b", r"\btrovami un altro\b",
            r"\bcambia profumo\b", r"\bcambiamo\b", r"\bpassiamo a\b",
            r"\bcerco un profumo\b", r"\bcerco una fragranza\b",
            r"\bvorrei un profumo\b", r"\bvorrei una fragranza\b",
            r"\bqualcos'altro\b", r"\bqualcosa di diverso\b", r"\bdiverso\b", r"\bdiversa\b"
        ]
        if any(re.search(p, q) for p in switch_patterns):
            return "CAMBIA"

        # 2. VALUTAZIONE DETERMINISTICA (Prezzo, note, piramide, durata, occasioni, pronomi)
        stay_patterns = [
            # Note e composizione olfattiva
            r"\bnote\b", r"\bnota\b", r"\bpiramide\b", r"\bingredienti\b", 
            r"\bcomposizione\b", r"\baccordi\b", r"\baccordo\b",
            
            # Pronomi riferiti al profumo attivo
            r"\bsu[oaei]\b",          # suo, sua, suoi, sue
            r"\bquest[oaei]\b",       # questo, questa, questi, queste
            r"\blo posso\b", r"\bla posso\b", r"\bsi puo\b", r"\bsi può\b",
            
            # Prezzo e costo
            r"\bcosta\b", r"\bcosto\b", r"\bprezzo\b", r"\beuro\b", r"\b€\b",
            
            # Performance e scia
            r"\bquanto dura\b", r"\bdura\b", r"\bdurata\b", r"\bpersistenza\b", r"\bproiezione\b", r"\bsillage\b",
            
            # Valutazione contestuale
            r"\bva bene\b", r"\bè adatto\b", r"\bè adatta\b", r"\bposso usarlo\b", r"\bposso usarla\b",
            r"\bper l'ufficio\b", r"\bin ufficio\b", r"\bal lavoro\b", r"\bdi giorno\b", r"\bdi sera\b",
            r"\bin spiaggia\b", r"\bal mare\b", r"\ba cena\b", r"\ba pranzo\b", r"\bin palestra\b",
            r"\bestiv[oae]\b", r"\binvernal[ei]\b", r"\bprimaveril[ei]\b", r"\bautunnal[ei]\b"
        ]
        if any(re.search(p, q) for p in stay_patterns):
            return "VALUTA"

        # 3. FALLBACK LLM: Se la frase è ambigua, interroga il modello rapido
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
            # FIX FONDAMENTALE: Se non c'è un'esplicita volontà di cambio, mantieni il profumo attivo
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

        # GESTIONE STEP GUIDATO CON RIPARTENZA DINAMICA
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

        # Flusso conversazione libera
        return self._handle_free_chat(user_query, session_id, max_price)

    def _generate_guided_recommendations(self, answers: list, session_id: str) -> dict:
        family = answers[0] if len(answers) > 0 else "Artistico"
        occasion = answers[1] if len(answers) > 1 else "Tutti i giorni"
        budget_str = answers[2] if len(answers) > 2 else "Nessun limite"

        # Parsing deterministico del budget per ChromaDB
        min_p = None
        max_p = None

        if "sotto 120" in budget_str.lower() or "< 120" in budget_str:
            max_p = 120.0
        elif "120" in budget_str and "200" in budget_str:
            min_p = 120.0
            max_p = 200.0
        elif "oltre 200" in budget_str.lower() or "> 200" in budget_str:
            min_p = 200.0
        # "Nessun limite" lascia min_p e max_p a None

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
                
                if i == 0:
                    first_product = {
                        "name": meta.get("name", ""),
                        "brand": meta.get("brand", "Profumeria Artistica"),
                        "price": meta.get("price", 0.0),
                        "add_to_cart_url": meta.get("add_to_cart_url", ""),
                        "document": doc
                    }

                context_items.append(
                    f"PROPOSTA {i+1}:\n"
                    f"- Nome: {meta['name']} ({meta.get('brand', 'Profumeria Artistica')})\n"
                    f"  Prezzo di vendita: {meta['price']} EUR\n"
                    f"  Link Carrello: {meta['add_to_cart_url']}\n"
                    f"  Profilo olfattivo: {doc}"
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
        active = self.active_perfumes.get(session_id)

        intent = self._determine_intent(user_query, active)
        is_follow_up = (intent == "VALUTA" and active is not None)

        print(f"\n[ROUTER DEBUG] Profumo attivo: '{active.get('name') if active else 'NESSUNO'}'")
        print(f"[ROUTER DEBUG] Domanda: '{user_query}' -> Decisione: {'SEGUI PRODOTTO (VALUTA)' if is_follow_up else 'CERCA NUOVO (CAMBIA)'}")

        if is_follow_up:
            context_str = (
                f"[PRODOTTO ATTUALMENTE DISCUSSO]\n"
                f"- Nome: {active['name']}\n"
                f"- Brand: {active.get('brand', 'Profumeria Artistica')}\n"
                f"- Prezzo di vendita ufficiale: {active['price']} EUR\n"
                f"- Link Carrello: {active['add_to_cart_url']}\n"
                f"- Profilo olfattivo e note: {active['document']}"
            )
            
            system_prompt = (
                "Sei un Maitre Parfumeur e critico olfattivo di altissimo livello in una profumeria artistica.\n"
                "Il tuo dovere principale è l'ONESTÀ e l'AUTOREVOLEZZA PROFESSIONALE: NON fare il compiacente e NON dire di sì a tutto.\n\n"
                "REGOLE CRITICHE PER IL GIUDIZIO E CHIARIMENTI (BLUF):\n"
                "1. DECISIONE NETTA NELLA PRIMA FRASE:\n"
                "   - Se la richiesta dell'utente è palesemente inadatta o sconveniente (es. note dolci/gourmand al mare d'estate, "
                "scie pesanti in palestra o ufficio, colonie effimere nel gelo invernale), BOCCIALA SENZA ESITAZIONE esordendo con fermezza ed eleganza: "
                "'Assolutamente no, te lo sconsiglio vivamente.', oppure 'No, è una combinazione che non funziona affatto.'.\n"
                "   - Se invece è adeguata (es. agrumato per l'estate), rispondi affermativamente confermando con sicurezza.\n"
                "   - NON usare formule ipocrite di compromesso come 'potrebbe andare bene se dosato poco'.\n"
                "2. MOTIVAZIONE TECNICA IN 1-2 FRASI: Spiega la ragione chimico-olfattiva concreta (calore/umidità, sillage, evaporazione molecolare).\n"
                "3. INDICAZIONE DI ROTTA IN CASO DI BOCCIATURA: Suggerisci in mezza frase che tipo di profilo servirebbe invece in quel contesto.\n"
                "4. GESTIONE DI PREZZO E LINK AL CARRELLO (REGOLA FONDAMENTALE):\n"
                "   - Nelle normali domande di chiarimento, parere o valutazione contestuale (es. 'va bene per le giornate estive?', 'quanto dura?', 'per l'ufficio?'), "
                "NON inserire né il prezzo né il link al carrello. Rispondi solo alla domanda posta in modo puntuale.\n"
                "   - Inserisci il prezzo e il link SOLO se l'utente richiede ESPLICITAMENTE il costo, dove acquistarlo o il link di acquisto.\n"
                "5. SINTESI TOTALE: Massimo 3 o 4 frasi concise. Niente paragrafi dispersivi."
            )

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history[-2:])
            messages.append({"role": "user", "content": f"RICHIESTA UTENTE: {user_query}\n\nCONTESTO:\n{context_str}"})

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
                    "add_to_cart_url": meta.get("add_to_cart_url", ""),
                    "document": doc
                }
                candidates_text.append(
                    f"[{pid}]\n"
                    f"Nome: {meta['name']}\n"
                    f"Brand: {meta.get('brand', 'Profumeria Artistica')}\n"
                    f"Prezzo: {meta['price']} EUR\n"
                    f"Link: {meta['add_to_cart_url']}\n"
                    f"Descrizione e Note: {doc}"
                )

            context_str = "\n\n".join(candidates_text)

            system_prompt = (
                "Sei un Maitre Parfumeur raffinato ed esperto di una boutique di nicchia.\n\n"
                "COMPITO DI SELEZIONE RIGOROSA:\n"
                "Hai a disposizione una lista di CANDIDATI estratti dal catalogo.\n"
                "1. Analizza la richiesta dell'utente.\n"
                "2. Scegli TRA I CANDIDATI ESATTAMENTE UN SOLO PRODOTTO che rispecchia REALMENTE e COERENTEMENTE la richiesta.\n"
                "3. REGOLA ANTI-CONTRADDIZIONE: Se un candidato è intenso/caldo, NON proporlo per richieste di freschezza/leggerezza.\n"
                "4. FORMATO RISPOSTA OBBLIGATORIO (Proposta di un nuovo profumo o alternativa):\n"
                "   [ID: PRODOTTO_X]\n"
                "   **Nome Profumo** di Brand\n"
                "   Descrizione raffinata e diretta (massimo 2-3 frasi) del perché è la scelta ideale per le sue note olfattive.\n"
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

        if not is_follow_up and "candidates_map" in locals():
            match = re.search(r"\[ID:\s*(PRODOTTO_\d+|NESSUNO)\]", reply, re.IGNORECASE)
            if match:
                selected_id = match.group(1).upper()
                if selected_id in candidates_map:
                    self.active_perfumes[session_id] = candidates_map[selected_id]
                    print(f"[ADVISOR] Profumo attivo registrato con successo: {candidates_map[selected_id]['name']}")
                reply = re.sub(r"\[ID:\s*(PRODOTTO_\d+|NESSUNO)\]\s*", "", reply).strip()
            else:
                self.active_perfumes[session_id] = candidates_map["PRODOTTO_1"]
                print(f"[ADVISOR FALLBACK] Profumo attivo registrato (primo candidato): {candidates_map['PRODOTTO_1']['name']}")

        self.sessions[session_id].append({"role": "user", "content": user_query})
        self.sessions[session_id].append({"role": "assistant", "content": reply})

        return {"reply": reply, "options": [], "step": None, "mode": "free"}