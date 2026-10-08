"""
test_scenarios_e2e.py - Test End-to-End di casi d'uso reali
Verifica: ricerca semantica reale con ChromaDB persistente e Groq attivo.
Ogni test è auto-consistente e può essere eseguito singolarmente.
"""

import os
from pathlib import Path
import pytest
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_PATH = BASE_DIR / "data" / "catalog.json"
CHROMA_DIR = BASE_DIR / "chroma_db"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY assente nel .env"),
    pytest.mark.skipif(not CATALOG_PATH.exists(), reason="data/catalog.json assente"),
    pytest.mark.skipif(not CHROMA_DIR.exists(), reason="chroma_db/ assente")
]


@pytest.fixture(scope="module")
def live_advisor():
    from src.advisor import FragranceAdvisor
    return FragranceAdvisor()


# ==============================================================================
# 1. RICERCA SPECIFICA CON NOTA E STAGIONALITÀ
# ==============================================================================

def test_scenario_note_and_season(live_advisor):
    session_id = "e2e_session_cannella"
    query = "vorrei un profumo invernale alla cannella"

    res = live_advisor.advise(query, session_id=session_id)

    assert res["mode"] == "free"
    assert len(res["products"]) == 1

    prod = res["products"][0]
    p_name = prod["name"]
    active = live_advisor.session_store.get_session(session_id)["active_perfume"]

    assert active is not None
    assert active["name"] == p_name

    traits = prod.get("traits", "").lower()
    story = prod.get("story", "").lower()
    key_notes = [n.lower() for n in prod.get("key_notes", [])]

    has_cannella = any("cannell" in n for n in key_notes) or "cannell" in story or "speziat" in traits
    assert has_cannella, f"La fragranza {p_name} non contiene accordi legati alla cannella."


# ==============================================================================
# 2. FOLLOW-UP SULLO STESSO PROFUMO (VALUTA SENZA CAMBIO PRODOTTO)
# ==============================================================================

def test_scenario_follow_up_stays_on_active(live_advisor):
    session_id = "e2e_session_followup"
    # Pre-condizione auto-consistente
    live_advisor.advise("consigliami un profumo alla vaniglia", session_id=session_id)
    active_before = live_advisor.session_store.get_session(session_id)["active_perfume"]
    assert active_before is not None

    follow_up_query = "quali sono le sue note olfattive e quanto dura sulla pelle?"
    res = live_advisor.advise(follow_up_query, session_id=session_id)

    # Risposta discorsiva: nessuna card aggiuntiva
    assert len(res["products"]) == 0
    assert len(res["reply"]) > 20

    active_after = live_advisor.session_store.get_session(session_id)["active_perfume"]
    assert active_after["name"] == active_before["name"]


# ==============================================================================
# 3. CAMBIO PROFUMO CON BUDGET RELATIVO PIÙ ECONOMICO (CAMBIA)
# ==============================================================================

def test_scenario_switch_with_relative_price(live_advisor):
    session_id = "e2e_session_switch"
    # Pre-condizione auto-consistente
    live_advisor.advise("consigliami un profumo orientale costoso", session_id=session_id)
    prev_perfume = live_advisor.session_store.get_session(session_id)["active_perfume"]
    prev_price = float(prev_perfume["price"])

    res = live_advisor.advise("vorrei qualcosa di più economico", session_id=session_id)

    assert len(res["products"]) == 1
    new_prod = res["products"][0]
    new_price = float(new_prod["price"])

    assert new_price < prev_price, f"Il nuovo profumo ({new_price}€) non è inferiore a {prev_price}€"


# ==============================================================================
# 4. GESTIONE RICHIESTE IMPOSSIBILI (NESSUNA ALLUCINAZIONE / [ID: NESSUNO])
# ==============================================================================

def test_scenario_nonexistent_request_graceful_rejection(live_advisor):
    session_id = "e2e_session_impossible"
    query = "cerco un profumo che odora esattamente di pizza al pomodoro e mozzarella"

    res = live_advisor.advise(query, session_id=session_id)

    # Nessun profumo del catalogo deve essere forzato
    assert len(res["products"]) == 0, f"Assegnato erroneamente un profumo: {res['products']}"
    assert len(res["reply"].strip()) > 15
    assert "[ID: NESSUNO]" not in res["reply"]

# ==============================================================================
# 5. PERCORSO GUIDATO COMPLETO CON RACCOMANDAZIONE FINALE (SLIDEOVER)
# ==============================================================================

def test_scenario_guided_flow_end_to_end(live_advisor):
    session_id = "e2e_session_full_quiz"

    res1 = live_advisor.advise("🎯 Guidami nella scelta", session_id=session_id)
    assert res1["step"] == 1

    res2 = live_advisor.advise("🪵 Legnoso o Intenso", session_id=session_id)
    assert res2["step"] == 2

    res3 = live_advisor.advise("Unisex", session_id=session_id)
    assert res3["step"] == 3

    res4 = live_advisor.advise("Sera / Occasioni speciali", session_id=session_id)
    assert res4["step"] == 4

    # Risposta alla domanda sul budget: conclusione del quiz
    res_final = live_advisor.advise("Nessun limite di budget", session_id=session_id)
    
    # 1. Il quiz si è concluso con successo
    assert res_final["step"] is None
    
    # 2. Il Maître Parfumeur presenta la selezione (fino a 3 fragranze affini)
    assert 1 <= len(res_final["products"]) <= 3
    
    # 3. Tutte le card devono essere di tipo 'slideover' per consentire l'esplorazione delle note
    for prod in res_final["products"]:
        assert prod["card_type"] == "slideover"
        assert "name" in prod
        assert "price" in prod
        assert "key_notes" in prod

    # 4. Deve essere registrato un profumo attivo per eventuali follow-up
    active = live_advisor.session_store.get_session(session_id)["active_perfume"]
    assert active is not None
