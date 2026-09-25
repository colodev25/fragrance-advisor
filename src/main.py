"""
main.py - FastAPI Server per il Consulente Olfattivo
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from src.advisor import FragranceAdvisor

app = FastAPI(title="Consulente Olfattivo AI")

# Configurazione CORS (consente chiamate da file locali o domini esterni)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inizializzazione del motore advisor
advisor = FragranceAdvisor()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    max_price: Optional[float] = None
    step_override: Optional[int] = None


@app.get("/")
def health_check():
    return {"status": "ok", "service": "Olfactive Advisor API"}


# Endpoint principale per la chat (gestisce sia /chat che /chat/)
@app.post("/chat")
@app.post("/chat/")
def chat_endpoint(req: ChatRequest):
    response = advisor.advise(
        user_query=req.message,
        session_id=req.session_id,
        max_price=req.max_price,
        step_override=req.step_override
    )
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="127.0.0.1", port=8000, reload=True)