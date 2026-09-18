from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

try:
    from src.advisor import FragranceAdvisor
except ModuleNotFoundError:
    from advisor import FragranceAdvisor

app = FastAPI(title="Fragrance Advisor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

advisor = FragranceAdvisor()

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default_session"
    max_price: Optional[float] = None

class ChatResponse(BaseModel):
    reply: str

@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Il messaggio non può essere vuoto.")
    
    reply_text = advisor.advise(
        user_query=request.message,
        session_id=request.session_id,
        max_price=request.max_price
    )
    return ChatResponse(reply=reply_text)