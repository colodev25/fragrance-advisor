"""
main.py - FastAPI Server per il Consulente Olfattivo Etualy
Focalizzato unicamente su chat, reset di sessione e health-check.
"""

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from src.rate_limit import InMemoryRateLimiter

BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DIR = BASE_DIR / "chroma_db"

logger = logging.getLogger("fragrance_advisor.api")

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_MESSAGE_LENGTH = 2_000
MAX_PRICE = 10_000.0


def _read_positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        logger.warning("Invalid %s value; using %s.", name, default)
        return default


def _read_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


RATE_LIMIT_ENABLED = _read_bool("RATE_LIMIT_ENABLED", True)
RATE_LIMIT_TRUST_PROXY_HEADERS = _read_bool("RATE_LIMIT_TRUST_PROXY_HEADERS")
CHAT_RATE_LIMIT_PER_MINUTE = _read_positive_int("CHAT_RATE_LIMIT_PER_MINUTE", 30)
RESET_RATE_LIMIT_PER_MINUTE = _read_positive_int("RESET_RATE_LIMIT_PER_MINUTE", 10)
rate_limiter = InMemoryRateLimiter()

advisor = None
startup_error: Optional[str] = None


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, headers: Optional[dict[str, str]] = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verifica e protegge l'integrità dell'indice vettoriale all'avvio del server."""
    global advisor, startup_error
    advisor = None
    startup_error = None
    logger.info("Starting Etualy olfactive advisor API.")

    try:
        from src.advisor import FragranceAdvisor
        advisor = FragranceAdvisor()
        logger.info("FragranceAdvisor is ready.")
    except Exception:
        startup_error = "initialization_failed"
        logger.exception("FragranceAdvisor could not be initialized.")

    yield
    advisor = None
    logger.info("Stopping Etualy olfactive advisor API.")


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
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    session_id: Optional[str] = Field(default="default", max_length=128)
    max_price: Optional[float] = Field(default=None, ge=0, le=MAX_PRICE)
    step_override: Optional[int] = Field(default=None, ge=1, le=4)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Il messaggio non può essere vuoto.")
        return value

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not SESSION_ID_PATTERN.fullmatch(value):
            raise ValueError("session_id può contenere solo lettere, numeri, trattini e underscore.")
        return value


class ResetRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        if not SESSION_ID_PATTERN.fullmatch(value):
            raise ValueError("session_id può contenere solo lettere, numeri, trattini e underscore.")
        return value


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "La richiesta non contiene dati validi.",
            }
        },
    )


def _client_identifier(request: Request) -> str:
    if RATE_LIMIT_TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()

    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request, route: str, limit: int) -> None:
    if not RATE_LIMIT_ENABLED:
        return

    allowed, retry_after = rate_limiter.allow(f"{route}:{_client_identifier(request)}", limit)
    if not allowed:
        raise ApiError(
            status_code=429,
            code="rate_limit_exceeded",
            message="Hai inviato troppe richieste. Riprova tra qualche istante.",
            headers={"Retry-After": str(retry_after)},
        )


@app.get("/")
def health_check():
    return {
        "status": "ok" if advisor is not None else "degraded",
        "service": "Etualy Olfactive Advisor API",
    }


@app.get("/health")
def readiness_check():
    if advisor is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": startup_error or "service_starting",
                    "message": "Il servizio non è ancora pronto.",
                }
            },
        )
    return {"status": "ready", "service": "Etualy Olfactive Advisor API"}


@app.post("/chat")
@app.post("/chat/")
def chat_endpoint(req: ChatRequest, request: Request):
    _enforce_rate_limit(request, "chat", CHAT_RATE_LIMIT_PER_MINUTE)
    if advisor is None:
        raise ApiError(503, startup_error or "service_starting", "Il servizio è in fase di avvio. Riprova tra qualche secondo.")

    try:
        return advisor.advise(
            user_query=req.message,
            session_id=req.session_id,
            max_price=req.max_price,
            step_override=req.step_override,
        )
    except Exception:
        logger.exception("Chat request failed.")
        raise ApiError(503, "advisor_unavailable", "La consulenza non è disponibile in questo momento. Riprova tra qualche istante.")


@app.post("/reset")
@app.post("/reset/")
def reset_endpoint(req: ResetRequest, request: Request):
    """Cancella lo stato della sessione su SQLite per ricominciare da zero."""
    _enforce_rate_limit(request, "reset", RESET_RATE_LIMIT_PER_MINUTE)
    if advisor is not None:
        try:
            advisor.reset_session(req.session_id)
        except Exception:
            logger.exception("Session reset failed.")
            raise ApiError(503, "session_reset_failed", "Non è stato possibile reimpostare la sessione. Riprova.")
    return {"status": "ok", "session_id": req.session_id, "message": "Sessione azzerata"}


if __name__ == "__main__":
    import uvicorn
    # In produzione reload=False contiene l'uso di RAM ed evita OOM
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)
