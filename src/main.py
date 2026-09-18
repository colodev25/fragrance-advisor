from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

try:
    from src.advisor import FragranceAdvisor
except ModuleNotFoundError:
    from advisor import FragranceAdvisor

app = FastAPI(title="Perfume Advisor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ISTANZA GLOBALE: fondamentale affinché la memoria persista tra le chiamate
advisor = FragranceAdvisor()

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    max_price: Optional[float] = None

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    sid = req.session_id if req.session_id else "default"
    # Log di debug nel terminale per verificare la sessione
    print(f"\n[DEBUG] Messaggio: '{req.message}' | Session ID: '{sid}'")
    
    reply = advisor.advise(
        user_query=req.message,
        session_id=sid,
        max_price=req.max_price
    )
    return {"reply": reply, "session_id": sid}

@app.post("/api/reset")
async def reset_endpoint(req: ChatRequest):
    sid = req.session_id if req.session_id else "default"
    if sid in advisor.sessions:
        del advisor.sessions[sid]
    if sid in advisor.active_perfumes:
        del advisor.active_perfumes[sid]
    return {"status": "reset", "session_id": sid}