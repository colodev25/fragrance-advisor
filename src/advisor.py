import os
from dotenv import load_dotenv
from openai import OpenAI
from search import FragranceSearchEngine

load_dotenv()

class FragranceAdvisor:
    def __init__(self):
        self.search_engine = FragranceSearchEngine()
        
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ValueError("GROQ_API_KEY non trovata nel file .env. Inseriscila per procedere.")

        # Inizializziamo il client OpenAI reindirizzandolo sui server gratuiti di Groq
        self.client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key
        )
        
        self.system_prompt = (
            "Sei un assistente esperto e raffinato di una profumeria di nicchia.\n"
            "Il tuo compito è consigliare al cliente la fragranza ideale in base ai suoi gusti, "
            "occasioni d'uso o sensazioni desiderate.\n\n"
            "REGOLE TASSATIVE:\n"
            "1. Consiglia ESCLUSIVAMENTE i prodotti presenti nella sezione 'PRODOTTI DISPONIBILI'. Non inventare nomi o brand.\n"
            "2. Spiega in modo elegante ed empatico perché la fragranza si adatta alla sua richiesta, citando le note olfattive chiave.\n"
            "3. Sii conciso (massimo 2 paragrafi per consiglio).\n"
            "4. Per ciascun profumo suggerito, includi sempre alla fine il link diretto per metterlo nel carrello formattato esattamente come:\n"
            "   [Aggiungi al Carrello](URL_FORNITO)"
        )

    def advise(self, user_query: str, max_price: float = None) -> str:
        # 1. Recupero semantico dal database vettoriale
        results = self.search_engine.search(query=user_query, max_price=max_price, n_results=2)
        
        if not results["ids"] or len(results["ids"][0]) == 0:
            return "Mi dispiace, al momento non ho trovato fragranze corrispondenti alle tue preferenze nel nostro catalogo."

        # 2. Costruzione del contesto estratto dal catalogo
        context_items = []
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            context_items.append(
                f"- Nome: {meta['name']} ({meta['brand']})\n"
                f"  Prezzo: {meta['price']} EUR\n"
                f"  Link Carrello: {meta['add_to_cart_url']}\n"
                f"  Profilo olfattivo: {results['documents'][0][i]}"
            )
        
        context_str = "\n\n".join(context_items)

        # 3. Generazione della risposta con LLM ad alte prestazioni gratuito
        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"RICHIESTA UTENTE: {user_query}\n\nPRODOTTI DISPONIBILI:\n{context_str}"}
            ],
            temperature=0.6
        )

        return response.choices[0].message.content

if __name__ == "__main__":
    advisor = FragranceAdvisor()
    
    # Esegui un test con una richiesta tipica da cliente
    domanda_test = "Cerco una fragranza fresca e marina che ricordi una giornata estiva al mare"
    print(f"\n--- Richiesta Cliente ---\n{domanda_test}\n")
    
    risposta = advisor.advise(domanda_test)
    print(f"--- Risposta Advisor ---\n{risposta}\n")