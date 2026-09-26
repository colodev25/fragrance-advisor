import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)

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


# ==============================================================================
# 1. TEST RISPOSTA CHAT LIBERA & CONTRATTO PAYLOAD
# ==============================================================================
@patch("src.main.advisor.advise")
def test_chat_endpoint_free_chat_success(mock_advise):
    mock_advise.return_value = {
        "reply": "Ti suggerisco una creazione marina iconica.",
        "options": [],
        "products": [MOCK_PRODUCT],
        "step": None,
        "mode": "free"
    }

    response = client.post("/chat", json={
        "message": "cerco un profumo marino",
        "session_id": "test_session_api"
    })

    assert response.status_code == 200
    data = response.json()

    # Verifica chiavi di primo livello
    assert "reply" in data
    assert "products" in data
    assert "options" in data
    assert "mode" in data
    assert data["mode"] == "free"

    # Verifica integrità della Product Card
    assert len(data["products"]) == 1
    prod = data["products"][0]
    required_card_keys = [
        "name", "brand", "price", "story", "key_notes", 
        "traits", "product_page_url", "add_to_cart_url"
    ]
    for key in required_card_keys:
        assert key in prod, f"Chiave mancante nella product card: {key}"

    assert isinstance(prod["key_notes"], list)
    assert len(prod["key_notes"]) > 0
    assert "•" in prod["traits"]


# ==============================================================================
# 2. TEST PERCORSO GUIDATO (STEP 1)
# ==============================================================================
@patch("src.main.advisor.advise")
def test_chat_endpoint_guided_step(mock_advise):
    mock_advise.return_value = {
        "reply": "Che tipo di sensazione o famiglia olfattiva preferisci?",
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

    response = client.post("/chat", json={
        "message": "guidami",
        "session_id": "test_guided_session"
    })

    assert response.status_code == 200
    data = response.json()

    assert data["step"] == 1
    assert data["mode"] == "guided"
    assert len(data["options"]) == 4
    assert len(data["products"]) == 0


# ==============================================================================
# 3. TEST VALIDAZIONE SCHEMA (BODY NON VALIDO)
# ==============================================================================
def test_chat_endpoint_validation_error():
    # Invio di un body privo del campo obbligatorio 'message' su /chat
    response = client.post("/chat", json={})
    assert response.status_code == 422