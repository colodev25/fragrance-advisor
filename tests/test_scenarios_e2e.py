import os
import pytest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = BASE_DIR / "data" / "catalog.json"
CHROMA_DIR = BASE_DIR / "chroma_db"

# Salta l'intera suite se non sono presenti i requisiti di produzione
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY mancante nel .env"),
    pytest.mark.skipif(not CATALOG_PATH.exists(), reason="data/catalog.json mancante"),
    pytest.mark.skipif(not CHROMA_DIR.exists(), reason="chroma_db/ non indicizzato")
]


@pytest.fixture(scope="module")
def live_advisor():
    """Inizializza una sola volta l'istanza live dell'advisor per l'intera sessione di test."""
    from src.advisor import FragranceAdvisor
    return FragranceAdvisor()


# ==============================================================================
# SCENARIO 1: Ricerca specifica con nota olfattiva e stagione
# ==============================================================================
def test_scenario_note_and_season(live_advisor):
    session_id = "e2e_session_cannella"
    query = "vorrei un profumo invernale alla cannella"

    res = live_advisor.advise(query, session_id=session_id)

    assert res["mode"] == "free"
    assert len(res["products"]) == 1

    prod = res["products"][0]
    p_name = prod["name"]
    active = live_advisor.active_perfumes.get(session_id)

    # Verifica che il profumo sia registrato in memoria attiva
    assert active is not None
    assert active["name"] == p_name

    # Verifica che la nota o il tema cannella/speziato sia presente nei dati del profumo
    traits = prod.get("traits", "").lower()
    story = prod.get("story", "").lower()
    key_notes = [n.lower() for n in prod.get("key_notes", [])]

    has_cannella = any("cannell" in n for n in key_notes) or "cannell" in story or "speziat" in traits
    assert has_cannella, f"Il profumo {p_name} non sembra contenere riferimenti alla cannella."


# ==============================================================================
# SCENARIO 2: Follow-up sullo stesso profumo (VALUTA senza cambio prodotto)
# ==============================================================================
def test_scenario_follow_up_stays_on_active(live_advisor):
    # Usa la stessa sessione dello Scenario 1
    session_id = "e2e_session_cannella"
    active_before = live_advisor.active_perfumes.get(session_id)
    assert active_before is not None, "Il profumo attivo dovrebbe essere impostato dallo scenario precedente."

    follow_up_query = "quali sono le sue note e quanto dura?"
    res = live_advisor.advise(follow_up_query, session_id=session_id)

    # Deve rispondere con testo senza generare nuove card (products vuoto)
    assert len(res["products"]) == 0
    assert len(res["reply"]) > 20

    # L'active perfume non deve essere cambiato
    active_after = live_advisor.active_perfumes.get(session_id)
    assert active_after["name"] == active_before["name"]


# ==============================================================================
# SCENARIO 3: Cambio profumo con vincolo di prezzo relativo (CAMBIA)
# ==============================================================================
def test_scenario_switch_with_relative_price(live_advisor):
    session_id = "e2e_session_cannella"
    prev_price = float(live_advisor.active_perfumes[session_id]["price"])

    res = live_advisor.advise("vorrei un'alternativa più economica", session_id=session_id)

    assert len(res["products"]) == 1
    new_prod = res["products"][0]
    new_price = float(new_prod["price"])

    # Il nuovo profumo deve costare meno del precedente
    assert new_price < prev_price, f"Il nuovo profumo ({new_price}€) non è più economico del precedente ({prev_price}€)"


# ==============================================================================
# SCENARIO 4: Fallback su richiesta impossibile / assente a catalogo
# ==============================================================================
def test_scenario_nonexistent_request_graceful_rejection(live_advisor):
    session_id = "e2e_session_impossible"
    query = "cerco un profumo che odora esattamente di pizza al pomodoro e mozzarella"

    res = live_advisor.advise(query, session_id=session_id)

    # Non deve forzare l'assegnazione di un profumo artistico non pertinente
    # L'advisor deve restituire products vuoto oppure una spiegazione cortese
    if len(res["products"]) > 0:
        # Se ChromaDB estrae un profumo, il Maître Parfumeur deve aver indicato [ID: NESSUNO]
        # scartando il payload nei rami di advisor
        assert False, f"L'advisor ha allucinato un profumo per la pizza: {res['products'][0]['name']}"

    assert len(res["reply"]) > 15