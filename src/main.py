"""
main.py - FastAPI Server per il Consulente Olfattivo Etualy
Focalizzato unicamente su chat, reset di sessione e health-check.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DIR = BASE_DIR / "chroma_db"

advisor = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verifica e protegge l'integrità dell'indice vettoriale all'avvio del server."""
    global advisor
    print("[*] Avvio Consulente Olfattivo FastAPI...")

    # Se ChromaDB non è presente sul filesystem del container, avvia il reindex automatico
    if not CHROMA_DIR.exists() or not any(CHROMA_DIR.iterdir()):
        print("[!] Cartella ChromaDB non trovata o vuota. Avvio generazione indice vettoriale...")
        try:
            from src.reindex import main as build_index
            build_index()
            print("[+] Indice ChromaDB auto-generato con successo al boot.")
        except Exception as e:
            print(f"[CRITICAL] Impossibile costruire l'indice vettoriale: {e}")

    # Inizializza l'istanza dell'advisor con l'indice garantito
    from src.advisor import FragranceAdvisor
    advisor = FragranceAdvisor()
    print("[+] FragranceAdvisor caricato e pronto a ricevere richieste.")

    yield
    print("[*] Arresto Consulente Olfattivo.")


app = FastAPI(title="Consulente Olfattivo AI - Etualy", lifespan=lifespan)

# Configurazione CORS conforme agli standard browser W3C
raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
is_wildcard = "*" in origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if is_wildcard else origins,
    allow_credentials=not is_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    max_price: Optional[float] = None
    step_override: Optional[int] = None


class ResetRequest(BaseModel):
    session_id: str


@app.get("/")
def health_check():
    return {"status": "ok", "service": "Etualy Olfactive Advisor API"}


@app.post("/chat")
@app.post("/chat/")
def chat_endpoint(req: ChatRequest):
    if advisor is None:
        return {"reply": "Il servizio è in fase di avvio, riprova tra qualche secondo.", "products": []}

    return advisor.advise(
        user_query=req.message,
        session_id=req.session_id,
        max_price=req.max_price,
        step_override=req.step_override
    )


@app.post("/reset")
@app.post("/reset/")
def reset_endpoint(req: ResetRequest):
    """Cancella lo stato della sessione su SQLite per ricominciare da zero."""
    if advisor is not None:
        advisor.reset_session(req.session_id)
    return {"status": "ok", "session_id": req.session_id, "message": "Sessione azzerata"}


if __name__ == "__main__":
    import uvicorn
    # In produzione reload=False contiene l'uso di RAM ed evita OOM
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)