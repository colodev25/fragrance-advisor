"""
test_parsers.py - Validazione della logica estrattiva, semantica e di stato
Verifica: pulizia note (ingest), stopwords, genere, stagione, vincoli prezzo, intent router e quiz guidato.
"""

from collections import defaultdict
from unittest.mock import MagicMock
import pytest

from src.ingest import clean_single_note, is_valid_note_item, clean_note_items
from src.advisor import FragranceAdvisor, STOPWORDS_NOTES, CANONICAL_NOTES
from src.session_store import SessionStore
from src.llm_resilience import ResilientGroqClient


@pytest.fixture
def advisor_mock(tmp_path):
    """Istanzia il vero FragranceAdvisor isolando il DB SQLite e mockando Groq."""
    db_file = tmp_path / "parsers_test_sessions.db"
    store = SessionStore(db_path=str(db_file))

    advisor = FragranceAdvisor(session_store=store)

    # Mock del client LLM configurato per simulare le decisioni del router intenti
    mock_client = MagicMock()
    mock_client.with_options.return_value = mock_client
    
    def fake_llm_completion(**kwargs):
        messages = kwargs.get("messages", [])
        content = messages[0]["content"].lower() if messages else ""
        resp = MagicMock()
        # Se la richiesta contiene verbi o parole di cambio
        if any(w in content for w in ["economico", "alternativa", "cambia", "diverso", "altro"]):
            resp.choices = [MagicMock(message=MagicMock(content="CAMBIA"))]
        else:
            resp.choices = [MagicMock(message=MagicMock(content="VALUTA"))]
        return resp

    mock_client.chat.completions.create.side_effect = fake_llm_completion
    advisor.client = mock_client
    advisor.resilient_client = ResilientGroqClient(mock_client, max_retries=1, base_delay=0.01)

    return advisor


# ==============================================================================
# 1. PULIZIA E SANITIZZAZIONE DELLE NOTE (ingest.py)
# ==============================================================================

def test_clean_single_note_removes_prefixes():
    assert clean_single_note("Si aprono con un esplosione esperidata di lime") == "Lime"
    assert clean_single_note("Alla mimosa") == "Mimosa"
    assert clean_single_note("Accordo di Ambra Grigia") == "Ambra Grigia"
    assert clean_single_note("Un tocco di pepe rosa") == "Pepe rosa"


def test_is_valid_note_item_filters_narrative_and_marketing():
    assert is_valid_note_item("Bergamotto") is True
    assert is_valid_note_item("Vaniglia del Madagascar") is True
    assert is_valid_note_item("Fiori d'Arancio") is True

    # Frasi e descrizioni narrative da scartare
    assert is_valid_note_item("Intensamente rinfrescanti") is False
    assert is_valid_note_item("La rotondità del musk si unisce ai toni legnosi") is False
    assert is_valid_note_item("Sensuale ed elegante") is False


def test_clean_note_items_pipeline():
    raw = "Si aprono con un esplosione di lime, Bergamotto, Intensamente rinfrescanti, 100 ml, EDP"
    cleaned = clean_note_items(raw)
    assert "Lime" in cleaned
    assert "Bergamotto" in cleaned
    assert "Intensamente rinfrescanti" not in cleaned
    assert "100 ml" not in cleaned
    assert "EDP" not in cleaned


# ==============================================================================
# 2. ESTRAZIONE DELLE NOTE E FILTRO STOPWORD (advisor.py)
# ==============================================================================

def test_extract_target_notes_excludes_stopwords(advisor_mock):
    query = "vorrei un profumo invernale alla cannella"
    notes = advisor_mock._extract_target_notes(query)
    assert "cannella" in notes
    assert "alla" not in notes
    assert "invernale" not in notes


# ==============================================================================
# 3. RICONOSCIMENTO DI GENERE (advisor.py)
# ==============================================================================

def test_detect_gender(advisor_mock):
    assert advisor_mock._detect_gender("Aventus", ["uomo", "per lui"]) == "Per Lui"
    assert advisor_mock._detect_gender("Soleil de Capri", ["soleil", "uomo"]) == "Per Lui"
    assert advisor_mock._detect_gender("Megamare", ["uomo", "donna"]) == "Unisex"
    assert advisor_mock._detect_gender("Silver Man", []) == "Per Lui"
    assert advisor_mock._detect_gender("Interlude Woman", []) == "Per Lei"
    assert advisor_mock._detect_gender("Silver Man", ["donna"]) == "Destinatario non dichiarato"
    assert advisor_mock._detect_gender("Interlude Woman", ["uomo"]) == "Destinatario non dichiarato"


# ==============================================================================
# 4. RICONOSCIMENTO STAGIONE (advisor.py)
# ==============================================================================

def test_detect_season(advisor_mock):
    assert advisor_mock._detect_season("Acquatica, Agrumata", []) == "Primavera / Estate (dedotta)"
    assert advisor_mock._detect_season("Cuoiata, Tabaccosa", []) == "Autunno / Inverno (dedotta)"
    assert advisor_mock._detect_season("", ["profumi invernali"]) == "Autunno / Inverno"
    assert advisor_mock._detect_season("", ["profumi estivi", "profumi invernali"]) == "Quattro Stagioni"


# ==============================================================================
# 5. PARSER PREZZI E BUDGET (advisor.py)
# ==============================================================================

def test_extract_price_constraints(advisor_mock):
    min_p, max_p, q = advisor_mock._extract_price_constraints("cerco un profumo sotto i 150€", None)
    assert min_p is None
    assert max_p == 149.99
    assert "150" not in q

    min_p, max_p, q = advisor_mock._extract_price_constraints("vorrei spendere tra 80 e 120 euro", None)
    assert min_p == 80.0
    assert max_p == 120.0

    active = {"price": 100.0, "name": "Profumo X"}
    min_p, max_p, _ = advisor_mock._extract_price_constraints("ne vorrei uno più economico", active)
    assert max_p == 99.99


# ==============================================================================
# 6. ROUTER INTENTI: VALUTA vs CAMBIA (advisor.py)
# ==============================================================================

def test_determine_intent_stay_vs_switch(advisor_mock):
    active_perfume = {"name": "Aventus", "price": 250.0}

    assert advisor_mock._determine_intent("quali sono le note di cuore?", active_perfume) == "VALUTA"
    assert advisor_mock._determine_intent("quanto dura sulla pelle?", active_perfume) == "VALUTA"
    assert advisor_mock._determine_intent("è adatto per l'ufficio?", active_perfume) == "VALUTA"

    assert advisor_mock._determine_intent("vorrei qualcosa di più economico", active_perfume) == "CAMBIA"
    assert advisor_mock._determine_intent("mostrami un'alternativa diversa", active_perfume) == "CAMBIA"
    assert advisor_mock._determine_intent("cambiamo profumo", active_perfume) == "CAMBIA"


# ==============================================================================
# 7. MACCHINA A STATI PERCORSO GUIDATO (advisor.py)
# ==============================================================================

def test_guided_flow_state_transitions(advisor_mock):
    session_id = "test_user_guided_flow"

    # Step 1
    res1 = advisor_mock.advise("guidami", session_id=session_id)
    assert res1["step"] == 1
    assert res1["mode"] == "guided"
    assert len(res1["options"]) > 0

    # Step 2
    res2 = advisor_mock.advise("🍋 Fresco o Agrumato", session_id=session_id)
    assert res2["step"] == 2
    assert advisor_mock.session_store.get_session(session_id)["guided_state"]["answers"] == ["🍋 Fresco o Agrumato"]

    # Step 3
    res3 = advisor_mock.advise("Per Lui", session_id=session_id)
    assert res3["step"] == 3
    assert advisor_mock.session_store.get_session(session_id)["guided_state"]["answers"] == ["🍋 Fresco o Agrumato", "Per Lui"]

    # Step 4
    res4 = advisor_mock.advise("Primavera / Estate", session_id=session_id)
    assert res4["step"] == 4
    assert advisor_mock.session_store.get_session(session_id)["guided_state"]["answers"] == ["🍋 Fresco o Agrumato", "Per Lui", "Primavera / Estate"]
