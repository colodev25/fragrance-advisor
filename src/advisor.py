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
        "options": ["Accessibile (sotto 150€)", "Profumeria Artistica d'Élite", "Nessun limite di budget"]
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
        Combina un filtro deterministico rapido (0 ms) con fallback sul modello leggero.
        """
        if not active_perfume:
            return "CAMBIA"

        q = query.lower().strip()

        # 1. CAMBIO ESPLICITO (Priorità massima)
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

        # 2. VALUTAZIONE DETERMINISTICA (Prezzo, durata, occasioni, idoneità, pronomi)
        stay_patterns = [
            r"\bcosta\b", r"\bcosto\b", r"\bprezzo\b", r"\beuro\b", r"\b€\b",
            r"\bquanto dura\b", r"\bdura\b", r"\bdurata\b", r"\bpersistenza\b", r"\bproiezione\b", r"\bsillage\b",
            r"\bva bene\b", r"\bè adatto\b", r"\bè adatta\b", r"\bposso usarlo\b", r"\bposso usarla\b",
            r"\bper l'ufficio\b", r"\bin ufficio\b", r"\bal lavoro\b", r"\bdi giorno\b", r"\bdi sera\b",
            r"\bin spiaggia\b", r"\bal mare\b", r"\ba cena\b", r"\ba pranzo\b", r"\bin palestra\b",
            r"\bestiv[oae]\b", r"\binvernal[ei]\b", r"\bprimaveril[ei]\b", r"\bautunnal[ei]\b",
            r"\bquesto\b", r"\bquesta\b", r"\blo posso\b", r"\bla posso\b", r"\bsi puo\b", r"\bsi può\b"
        ]
        if any(re.search(p, q) for p in stay_patterns):
            return "VALUTA"

        # 3. FALLBACK: Se la frase è ambigua, interroga il modello rapido
        prompt = (
            f"Stiamo parlando del profumo: '{active_perfume['name']}' ({active_perfume.get('brand', '')}).\n"
            f"Messaggio del cliente: \"{query}\"\n\n"
            "Regola:\n"
            "- Rispondi 'VALUTA' se chiede opinioni, chiarimenti o dettagli riferiti a questo profumo.\n"
            "- Rispondi 'CAMBIA' solo se chiede di vedere una nuova o diversa fragranza.\n"
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
            return "VALUTA" if "VALUTA" in decision else "CAMBIA"
        except Exception:
            return "VALUTA"

    def advise(self, user_query: str, session_id: str = "default", max_price: float = None) -> dict:
        if not session_id:
            session_id = "default"

        query_clean = user_query.strip()
        q_lower = query_clean.lower()
        state = self.guided_states[session_id]

        # Riconoscimento avvio/riavvio percorso guidato
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
                "mode": "guided"
            }

        # Riconoscimento passaggio a chat libera
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
                "mode": "free"
            }

        # Gestione step del questionario guidato
        if state["step"] is not None:
            current_step = state["step"]
            state["answers"].append(query_clean)

            if current_step < 3:
                next_step = current_step + 1
                state["step"] = next_step
                return {
                    "reply": GUIDED_STEPS[next_step]["question"],
                    "options": GUIDED_STEPS[next_step]["options"],
                    "mode": "guided"
                }
            else:
                state["step"] = None
                answers = state["answers"]
                return self._generate_guided_recommendations(answers, session_id)

        # Flusso conversazione libera
        return self._handle_free_chat(user_query, session_id, max_price)

    def _generate_guided_recommendations(self, answers: list, session_id: str) -> dict:
        family = answers[0] if len(answers) > 0 else "Artistico"
        occasion = answers[1] if len(answers) > 1 else "Tutti i giorni"
        budget = answers[2] if len(answers) > 2 else "Standard"

        limit_price = 150.0 if "150" in budget else None
        search_prompt = f"Profumo {family} ideale per {occasion}. Mood e intensità: {budget}"

        results = self.search_engine.search(query=search_prompt, max_price=limit_price, n_results=3)

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
                    f"  Prezzo: {meta['price']} EUR\n"
                    f"  Link Carrello: {meta['add_to_cart_url']}\n"
                    f"  Profilo olfattivo: {doc}"
                )

        if not context_items:
            return {
                "reply": "Non ho trovato fragranze a catalogo perfettamente corrispondenti a questa combinazione. Prova a selezionare un'altra famiglia olfattiva!",
                "options": ["🎯 Ricomincia percorso guidato", "💬 Fai una domanda libera"],
                "mode": "free"
            }

        if first_product:
            self.active_perfumes[session_id] = first_product

        context_str = "\n\n".join(context_items)

        prompt = (
            f"L'utente ha completato il percorso guidato con queste preferenze:\n"
            f"- Famiglia olfattiva: {family}\n"
            f"- Occasione/Uso: {occasion}\n"
            f"- Budget/Stile: {budget}\n\n"
            f"PRODOTTI REALI PRESENTI A CATALOGO:\n{context_str}\n\n"
            "REGOLE ANTI-ALLUCINAZIONE:\n"
            "1. Presenta ESCLUSIVAMENTE i prodotti elencati sopra. NON inventare nomi, marchi o profumi non presenti nel testo.\n"
            "2. Per ciascun profumo indica nome in grassetto e brand (es. **Nome Profumo** di Brand), note salienti e il link esatto:\n"
            "   [Aggiungi al Carrello](URL_FORNITO)\n"
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
                f"- Nome: {active['name']} ({active['brand']})\n"
                f"  Prezzo di vendita ufficiale: {active['price']} EUR\n"
                f"  Link Carrello: {active['add_to_cart_url']}\n"
                f"  Profilo olfattivo e note: {active['document']}"
            )
            
            system_prompt = (
                "Sei un Maitre Parfumeur e critico olfattivo di altissimo livello in una profumeria artistica.\n"
                "Il tuo dovere principale è l'ONESTÀ e l'AUTOREVOLEZZA PROFESSIONALE: NON fare il compiacente e NON dire di sì a tutto.\n\n"
                "REGOLE CRITICHE PER IL GIUDIZIO (BLUF):\n"
                "1. DECISIONE NETTA NELLA PRIMA FRASE:\n"
                "   - Se l'utente chiede il PREZZO o COSTO, indicalo chiaramente nella prima frase riportando il 'Prezzo di vendita ufficiale'.\n"
                "   - Se la richiesta dell'utente è palesemente inadatta, stucchevole o sconveniente (es. note dolci/gourmand/calde/pesanti "
                "in spiaggia sotto il sole, profumi opulenti/animalici in una piccola palestra o in corsia d'ospedale, colonie agrumate ed effimere "
                "nel freddo pungente di una notte invernale), BOCCIALA SENZA ESITAZIONE esordendo con fermezza ed eleganza mantenendo sempre un tono gentile: "
                "'Assolutamente no, te lo sconsiglio vivamente.', oppure 'No, è una combinazione che non funziona affatto.'.\n"
                "   - NON usare formule ipocrite di compromesso come 'potrebbe andare bene se dosato poco' o 'con moderazione si può fare tutto'. "
                "Se una fragranza rischia di diventare nauseante, pesante o svanire subito, dillo chiaramente.\n"
                "2. MOTIVAZIONE TECNICA IN 1-2 FRASI: Spiega la ragione chimico-olfattiva concreta (es. calore/umidità che fanno virare le note gourmand "
                "rendendole asfissianti, sillage invadente per un ambiente chiuso, o temperatura troppo rigida che blocca le molecole volatili).\n"
                "3. INDICAZIONE DI ROTTA: Chiudi suggerendo in mezza frase che tipo di profilo servirebbe invece in quel contesto "
                "(es. 'Per il mare punta su accordi marini, salati o agrumati trasparenti').\n"
                "4. LINK CARRELLO OBBLIGATORIO: Quando stai parlando di un singolo prodotto, proponendolo come soluzione al cliente, "
                "chiudi SEMPRE il messaggio riportando in una riga separata il link di acquisto formattato ESATTAMENTE come:\n"
                "   [Aggiungi al Carrello](URL_FORNITO)\n"
                " EVITA di inserire il link per l'aggiunta al carrello quando stai proponendo più alternative nello stesso messaggio, o quando stai criticando un prodotto senza proporne uno alternativo.\n"
                "5. SINTESI TOTALE: Massimo 3 o 4 frasi concise. Niente paragrafi troppo lunghi e dispersivi."
            )

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history[-2:])
            messages.append({"role": "user", "content": f"RICHIESTA UTENTE: {user_query}\n\nCONTESTO:\n{context_str}"})

        else:
            # NUOVA RICERCA: Pool di 5 candidati da ChromaDB per selezione coerente
            results = self.search_engine.search(query=user_query, max_price=max_price, n_results=5)
            
            if not results["ids"] or len(results["ids"][0]) == 0:
                fallback_reply = (
                    "Non ho trovato a catalogo una fragranza che corrisponda a queste specifiche caratteristiche. "
                    "Puoi provare a indicare una famiglia olfattiva più generica oppure iniziare il nostro percorso guidato."
                )
                self.sessions[session_id].append({"role": "user", "content": user_query})
                self.sessions[session_id].append({"role": "assistant", "content": fallback_reply})
                return {"reply": fallback_reply, "options": ["🎯 Guidami nella scelta"], "mode": "free"}

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
                "4. FORMATO RISPOSTA OBBLIGATORIO:\n"
                "   - Inizia con il tag identificativo: [ID: PRODOTTO_X]\n"
                "   - Subito dopo, nella prima riga, scrivi il nome del profumo e il brand in grassetto (es. **Nome Profumo** di Brand).\n"
                "   - Prosegui con una spiegazione raffinata e diretta (massimo 2-3 frasi) del perché è la scelta ideale per le sue note.\n"
                "   - Chiudi sempre riportando in una riga separata il link carrello:\n"
                "     [Aggiungi al Carrello](URL_FORNITO)\n"
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

        # Se era una nuova ricerca, aggancia con precisione il profumo scelto
        if not is_follow_up and "candidates_map" in locals():
            match = re.search(r"\[ID:\s*(PRODOTTO_\d+|NESSUNO)\]", reply, re.IGNORECASE)
            if match:
                selected_id = match.group(1).upper()
                if selected_id in candidates_map:
                    self.active_perfumes[session_id] = candidates_map[selected_id]
                    print(f"[ADVISOR] Profumo attivo registrato con successo: {candidates_map[selected_id]['name']}")
                # Rimuove solo il tag tecnico di routing, lasciando intatto nome in grassetto e brand
                reply = re.sub(r"\[ID:\s*(PRODOTTO_\d+|NESSUNO)\]\s*", "", reply).strip()
            else:
                self.active_perfumes[session_id] = candidates_map["PRODOTTO_1"]
                print(f"[ADVISOR FALLBACK] Profumo attivo registrato (primo candidato): {candidates_map['PRODOTTO_1']['name']}")

        self.sessions[session_id].append({"role": "user", "content": user_query})
        self.sessions[session_id].append({"role": "assistant", "content": reply})

        return {"reply": reply, "options": [], "mode": "free"}