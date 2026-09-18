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
        
        self.system_prompt = (
            "Sei un assistente esperto e raffinato di una profumeria di nicchia.\n"
            "Il tuo compito è guidare il cliente nella scelta della fragranza ideale o chiarire dubbi sui prodotti a catalogo.\n\n"
            "REGOLE TASSATIVE SULLA VERIDICITÀ DELLE NOTE:\n"
            "1. FEDELTÀ OLFATTIVA: Se l'utente richiede esplicitamente una specifica nota (es. 'fico', 'zenzero', 'caramello'), "
            "e NESSUNO dei prodotti presenti nel contesto la contiene espressamente, NON consigliare un profumo alternativo spacciandolo "
            "per quello richiesto. Spiega invece con cortesia che al momento non è disponibile a catalogo una fragranza con quella nota specifica, "
            "e proponi semmai un accordo affine chiarendo che si tratta di una famiglia diversa.\n"
            "2. Se nel contesto è presente [MODALITÀ APPROFONDIMENTO PRODOTTO CORRENTE], rispondi valutando ESCLUSIVAMENTE "
            "quel prodotto senza cercare o proporre altre fragranze.\n"
            "3. Quando consigli un profumo, proponine SOLO UNO ideale e chiudi con il link:\n"
            "   [Aggiungi al Carrello](URL_FORNITO)\n"
            "4. Sii elegante, onesto e conciso (1-2 paragrafi)."
        )

    def _should_stay_on_current_perfume(self, user_query: str, active_perfume: dict, history: list) -> bool:
        """Determina in modo deterministico se rimanere sul profumo attivo."""
        if not active_perfume or not history:
            return False

        q = user_query.lower().strip()

        # Segnali espliciti di volontà di cambio prodotto
        switch_signals = [
            "altro", "altra", "altri", "altre",
            "cambia", "cambiamo", "cambiare",
            "invece", "differente", "divers",
            "cerco un altro", "mostrami un altro", "consigliami un altro",
            "passiamo a", "un profumo diverso", "un profumo differente", "un profumo nuovo",
            "non mi piace", "non è adatto", "non va bene", "non mi convince", "non fa per me", "non è quello che cerco",
            "voglio un altro", "vorrei un altro", "mi serve un altro"
        ]

        # Se l'utente chiede espressamente di cambiare o vedere altro -> Nuova Ricerca
        if any(sig in q for sig in switch_signals):
            return False

        # Altrimenti, se abbiamo un profumo attivo in memoria, qualsiasi domanda
        # (prezzo, note, stagione, persistenza, 'questo', 'e per...', 'va bene')
        # rimane ancorata sul prodotto corrente
        return True
    
    def advise(self, user_query: str, session_id: str = "default", max_price: float = None) -> str:
        # Se session_id arriva vuoto o None, usa sempre un id coerente
        if not session_id:
            session_id = "default"

        history = self.sessions[session_id]
        active = self.active_perfumes.get(session_id)

        # 1. Decisione dell'intento
        is_follow_up = self._should_stay_on_current_perfume(user_query, active, history)

        print(f"[ADVISOR DEBUG] Profumo attivo in memoria: {active.get('name') if active else 'NESSUNO'}")
        print(f"[ADVISOR DEBUG] Decisione intento: {'APPROFONDIMENTO (Bypass Chroma)' if is_follow_up else 'NUOVA RICERCA'}")

        context_str = ""

        if is_follow_up:
            # BLOCCA CHROMA: Passiamo solo ed esclusivamente il profumo attivo
            context_str = (
                f"[MODALITÀ APPROFONDIMENTO PRODOTTO CORRENTE]\n"
                f"- Nome: {active['name']} ({active['brand']})\n"
                f"  Prezzo: {active['price']} EUR\n"
                f"  Link Carrello: {active['add_to_cart_url']}\n"
                f"  Dettagli olfattivi: {active['document']}"
            )
        else:
            # Nuova ricerca sul catalogo vettoriale
            results = self.search_engine.search(query=user_query, max_price=max_price, n_results=1)

            if results["ids"] and len(results["ids"][0]) > 0:
                meta = results["metadatas"][0][0]
                doc = results["documents"][0][0]

                # Salviamo SUBITO il nuovo profumo attivo come riferimento principale
                self.active_perfumes[session_id] = {
                    "name": meta.get("name", ""),
                    "brand": meta.get("brand", "Profumeria Artistica"),
                    "price": meta.get("price", 0.0),
                    "add_to_cart_url": meta.get("add_to_cart_url", ""),
                    "document": doc
                }

                context_str = (
                    f"[PRODOTTO CONSIGLIATO DAL CATALOGO]\n"
                    f"- Nome: {meta['name']} ({meta['brand']})\n"
                    f"  Prezzo: {meta['price']} EUR\n"
                    f"  Link Carrello: {meta['add_to_cart_url']}\n"
                    f"  Dettagli olfattivi: {doc}"
                )
            else:
                context_str = "Nessun prodotto trovato nel catalogo."

        # 2. Generazione della risposta finale con il modello 120b
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(history[-4:])
        messages.append({
            "role": "user",
            "content": f"RICHIESTA UTENTE: {user_query}\n\nCONTESTO PRODOTTO:\n{context_str}"
        })

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=0.2
        )

        bot_reply = response.choices[0].message.content

        # 3. Memorizza lo storico della conversazione
        self.sessions[session_id].append({"role": "user", "content": user_query})
        self.sessions[session_id].append({"role": "assistant", "content": bot_reply})

        return bot_reply