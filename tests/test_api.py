"""
test_api.py - Suite di collaudo per l'interfaccia HTTP FastAPI
Verifica: contratti JSON, routing chat/reset, CORS headers e gestione errori.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from src.main import CHAT_RATE_LIMIT_PER_MINUTE, app, rate_limiter

MOCK_PRODUCT = {
    "name": "Acqua di Sale",
    "brand": "Profumum Roma",
    "price": 250.0,
    "family": "Marina",
    "ptype": "Profumo",
    "add_to_cart_url": "https://store.it/cart/123:1",
    "product_page_url": "https://store.it/products/acqua-di-sale",
    "image_url": "https://store.it/img.jpg",
    "card_type": "standard",
    "story": "Un'armonia marina costruita attorno ad accordi salini e mirto.",
    "key_notes": ["Sale Marino", "Mirto", "Alghe"],
    "traits": "Profumo • Unisex • Primavera / Estate",
    "description": "Un'armonia marina costruita attorno ad accordi salini e mirto."
}


@pytest.fixture
def api_client():
    """Client di test con supporto completo al context manager per il lifespan."""
    rate_limiter.reset()
    with TestClient(app) as client:
        yield client


# ==============================================================================
# 1. HEALTH CHECK & ENDPOINT ROOT
# ==============================================================================

def test_health_check_endpoint(api_client):
    """Verifica che la root API risponda con status 200 e identità del servizio."""
    response = api_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data


# ==============================================================================
# 2. CHAT ENDPOINT: CONTRATTO CHAT LIBERA & CARDS PRODOTTO
# ==============================================================================

def test_chat_endpoint_free_chat_contract(api_client):
    """Verifica la serializzazione completa del payload per la chat libera."""
    mock_advisor = MagicMock()
    mock_advisor.advise.return_value = {
        "reply": "Ti suggerisco una creazione marina iconica.",
        "options": [],
        "products": [MOCK_PRODUCT],
        "step": None,
        "mode": "free"
    }

    with patch("src.main.advisor", mock_advisor):
        response = api_client.post("/chat", json={
            "message": "cerco un profumo marino",
            "session_id": "test_session_api",
            "max_price": 300.0
        })

    assert response.status_code == 200
    data = response.json()

    # Verifica contratto di primo livello
    assert "reply" in data and len(data["reply"]) > 0
    assert "products" in data and len(data["products"]) == 1
    assert "options" in data and isinstance(data["options"], list)
    assert data.get("mode") == "free"
    assert data.get("step") is None

    # Verifica completezza dei campi della Product Card
    prod = data["products"][0]
    required_fields = [
        "name", "brand", "price", "story", "key_notes",
        "traits", "product_page_url", "add_to_cart_url", "image_url"
    ]
    for field in required_fields:
        assert field in prod, f"Campo obbligatorio assente nella card: {field}"
    assert isinstance(prod["key_notes"], list)
    assert len(prod["key_notes"]) >= 1


# ==============================================================================
# 3. CHAT ENDPOINT: PERCORSO GUIDATO (STEP E OPZIONI)
# ==============================================================================

def test_chat_endpoint_guided_step_contract(api_client):
    """Verifica il comportamento dell'endpoint durante uno step del quiz guidato."""
    mock_advisor = MagicMock()
    mock_advisor.advise.return_value = {
        "reply": "Che tipo di fragranza preferisci?",
        "options": [
            "🍋 Fresco o Agrumato",
            "🌸 Floreale o Fruttato",
            "🍦 Dolce o Caldo",
            "🪵 Legnoso o Intenso"
        ],
        "products": [],
        "step": 1,
        "mode": "guided"
    }

    with patch("src.main.advisor", mock_advisor):
        # Test con rotta alternativa con slash finale (/chat/)
        response = api_client.post("/chat/", json={
            "message": "🎯 Guidami nella scelta",
            "session_id": "test_guided_api"
        })

    assert response.status_code == 200
    data = response.json()

    assert data["step"] == 1
    assert data["mode"] == "guided"
    assert len(data["options"]) == 4
    assert len(data["products"]) == 0
    assert "🍋 Fresco o Agrumato" in data["options"]


# ==============================================================================
# 4. RESET ENDPOINT: AZZERAMENTO SESSIONE REMOTA
# ==============================================================================

def test_reset_endpoint_invokes_advisor_cleanup(api_client):
    """Verifica che la chiamata POST a /reset richiami il metodo reset_session."""
    mock_advisor = MagicMock()

    with patch("src.main.advisor", mock_advisor):
        response = api_client.post("/reset", json={"session_id": "user_to_reset_123"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["session_id"] == "user_to_reset_123"
    mock_advisor.reset_session.assert_called_once_with("user_to_reset_123")


# ==============================================================================
# 5. VALIDAZIONE ERRORI SCHEMA PYDANTIC (422 UNPROCESSABLE ENTITY)
# ==============================================================================

def test_chat_endpoint_missing_required_fields(api_client):
    """Invio di un payload privo del campo 'message'."""
    response = api_client.post("/chat", json={"session_id": "only_session"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_reset_endpoint_missing_session_id(api_client):
    """Invio di un body vuoto all'endpoint /reset."""
    response = api_client.post("/reset", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_chat_endpoint_rejects_blank_or_unsafe_inputs(api_client):
    blank_message = api_client.post("/chat", json={"message": "   "})
    invalid_session = api_client.post(
        "/chat",
        json={"message": "Consigliami un profumo", "session_id": "session id con spazi"},
    )

    assert blank_message.status_code == 422
    assert invalid_session.status_code == 422
    assert blank_message.json()["error"]["code"] == "validation_error"


def test_chat_endpoint_rate_limit(api_client):
    mock_advisor = MagicMock()
    mock_advisor.advise.return_value = {
        "reply": "Risposta di test.",
        "options": [],
        "products": [],
        "step": None,
        "mode": "free",
    }

    with patch("src.main.advisor", mock_advisor):
        for _ in range(CHAT_RATE_LIMIT_PER_MINUTE):
            response = api_client.post("/chat", json={"message": "Test rate limit", "session_id": "rate_test"})
            assert response.status_code == 200

        blocked = api_client.post("/chat", json={"message": "Test rate limit", "session_id": "rate_test"})

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(blocked.headers["retry-after"]) >= 1


# ==============================================================================
# 6. VERIFICA INTEGRAZIONE CORS POLICY
# ==============================================================================

def test_cors_preflight_headers(api_client):
    """Verifica che il server risponda alle chiamate preflight OPTIONS del browser."""
    response = api_client.options(
        "/chat",
        headers={
            "Origin": "https://etualy.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type"
        }
    )
    assert response.status_code == 200
    # Deve contenere l'header di autorizzazione per il widget
    assert "access-control-allow-origin" in response.headers
