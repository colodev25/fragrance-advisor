import os
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
        
        # session_id -> list di messaggi
        self.sessions = defaultdict(list)
        
        self.system_prompt = (
            "Sei un assistente esperto e raffinato di una profumeria di nicchia.\n"
            "Il tuo compito è guidare il cliente nella scelta della fragranza ideale in base ai suoi gusti, "
            "occasioni d'uso o chiarire dubbi sui prodotti discussi.\n\n"
            "REGOLE TASSATIVE:\n"
            "1. Consiglia o fornisci dettagli ESCLUSIVAMENTE sui prodotti presenti nel contesto fornito. Non inventare dati.\n"
            "2. Se l'utente chiede chiarimenti, prezzi o dettagli su un profumo appena discusso, rispondi con precisione sul prodotto corretto.\n"
            "3. Sii conciso, elegante e chiaro (massimo 1-2 brevi paragrafi).\n"
            "4. Quando menzioni un prodotto specifico, fornisci sempre alla fine il link per metterlo nel carrello formattato come:\n"
            "   [Aggiungi al Carrello](URL_FORNITO)"
        )

    def _rewrite_query(self, user_query: str, history: list) -> str:
        """Riscrive una domanda ambigua (es. 'quanto costa?') unendola al contesto precedente."""
        if not history:
            return user_query

        # Usiamo un prompt snello per riformulare la ricerca in base alla cronologia
        messages = [
            {
                "role": "system", 
                "content": (
                    "Dato lo storico della conversazione e l'ultimo messaggio dell'utente, formula una singola "
                    "frase di ricerca autonoma per trovare i prodotti corretti a catalogo. "
                    "Se l'utente fa una domanda di approfondimento su un profumo precedente (es. 'quanto costa?', 'che note ha?'), "
                    "includi il nome del profumo a cui si riferisce. "
                    "Rispondi SOLO con la frase di ricerca riformulata, senza aggiungere commenti."
                )
            }
        ]
        # Passa solo gli ultimi 2-3 scambi per velocità
        messages.extend(history[-3:])
        messages.append({"role": "user", "content": user_query})

        res = self.client.chat.completions.create(
            model="openai/gpt-oss-20b", # Usiamo il modello compatto per latenza minima (<200ms)
            messages=messages,
            temperature=0.1
        )
        rewritten = res.choices[0].message.content.strip()
        return rewritten

    def advise(self, user_query: str, session_id: str = "default", max_price: float = None) -> str:
        history = self.sessions[session_id]

        # 1. Riscrittura intelligente della query basata sullo storico
        search_query = self._rewrite_query(user_query, history)
        
        # 2. Ricerca sul database vettoriale con la query corretta
        results = self.search_engine.search(query=search_query, max_price=max_price, n_results=2)
        
        context_items = []
        if results["ids"] and len(results["ids"][0]) > 0:
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i]
                context_items.append(
                    f"- Nome: {meta['name']} ({meta['brand']})\n"
                    f"  Prezzo: {meta['price']} EUR\n"
                    f"  Link Carrello: {meta['add_to_cart_url']}\n"
                    f"  Profilo olfattivo: {results['documents'][0][i]}"
                )
        context_str = "\n\n".join(context_items) if context_items else "Nessun prodotto correlato trovato."

        # 3. Composizione del prompt per la risposta finale
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(history[-4:])
        messages.append({
            "role": "user",
            "content": f"DOMANDA UTENTE: {user_query}\n\nPRODOTTI CORRELATI DAL CATALOGO:\n{context_str}"
        })

        response = self.client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=0.5
        )

        bot_reply = response.choices[0].message.content

        # 4. Aggiorna lo storico
        self.sessions[session_id].append({"role": "user", "content": user_query})
        self.sessions[session_id].append({"role": "assistant", "content": bot_reply})

        return bot_reply