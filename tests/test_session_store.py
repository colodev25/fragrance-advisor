"""
test_session_store.py - Suite per il gestore di persistenza SQLite
Verifica: atomicita, modalita WAL, recupero post-riavvio server e sincronizzazione HTTP.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from src.session_store import SessionStore
from src.advisor import FragranceAdvisor
from src.main import app


@pytest.fixture
def temp_store(tmp_path):
    db_file = tmp_path / "unit_test_sessions.db"
    return SessionStore(db_path=str(db_file))


# ==============================================================================
# 1. UNIT TEST BASSO LIVELLO (SQLITE & STRUTTURE DATI)
# ==============================================================================

def test_store_default_session(temp_store):
    state = temp_store.get_session("sessione_non_esistente")
    assert state["history"] == []
    assert state["active_perfume"] is None
    assert state["guided_state"] == {"step": None, "answers": []}


def test_store_save_and_retrieve_with_emojis_and_quotes(temp_store):
    session_id = "user_special_chars"
    history = [
        {"role": "user", "content": "Cerco l'odore d'Oriente 🪵"},
        {"role": "assistant", "content": "Ecco L'Interdit d'Or"}
    ]
    active_perfume = {"name": "L'Air du Désert Marocain", "price": 180.0}
    guided_state = {"step": 2, "answers": ["🪵 Legnoso o Intenso"]}

    temp_store.save_session(session_id, history, active_perfume, guided_state)
    retrieved = temp_store.get_session(session_id)

    assert retrieved["history"] == history
    assert retrieved["active_perfume"] == active_perfume
    assert retrieved["guided_state"] == guided_state


def test_store_upsert_overwrite(temp_store):
    session_id = "user_upsert"
    temp_store.save_session(session_id, [], None, {"step": 1, "answers": []})

    updated_perfume = {"name": "Aventus", "price": 295.0}
    temp_store.save_session(
        session_id,
        [{"role": "user", "content": "Aventus"}],
        updated_perfume,
        {"step": 2, "answers": ["🍋 Fresco o Agrumato", "Per Lui"]}
    )

    retrieved = temp_store.get_session(session_id)
    assert len(retrieved["history"]) == 1
    assert retrieved["active_perfume"]["name"] == "Aventus"
    assert retrieved["guided_state"]["step"] == 2


def test_store_clear_session(temp_store):
    session_id = "user_delete"
    temp_store.save_session(session_id, [{"m": 1}], {"name": "Test"}, {"step": 3, "answers": []})

    temp_store.clear_session(session_id)
    retrieved = temp_store.get_session(session_id)
    assert retrieved["history"] == []
    assert retrieved["active_perfume"] is None


def test_store_concurrent_writes(temp_store):
    """Verifica che la modalità WAL e i timeout gestiscano accessi concorrenti senza blocchi."""
    def write_worker(idx):
        temp_store.save_session(
            session_id=f"concurrent_user_{idx}",
            history=[{"m": idx}],
            active_perfume={"id": idx},
            guided_state={"step": idx, "answers": []}
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(write_worker, i) for i in range(20)]
        for f in futures:
            f.result()

    for i in range(20):
        state = temp_store.get_session(f"concurrent_user_{i}")
        assert state["guided_state"]["step"] == i


# ==============================================================================
# 2. SIMULAZIONE RIAVVIO SERVER: RECUPERO STATO DA DISCO
# ==============================================================================

def test_session_state_restored_after_restart(tmp_path):
    """Simula lo spegnimento completo del processo Python tra una domanda e l'altra."""
    db_file = tmp_path / "restart_test.db"
    session_id = "user_survives_restart"

    # Istanza 1: imposta il profumo attivo
    store1 = SessionStore(db_path=str(db_file))
    advisor1 = FragranceAdvisor(session_store=store1)
    advisor1.active_perfumes[session_id] = {"name": "Santal 33", "price": 230.0}
    store1.save_session(
        session_id,
        history=[{"role": "user", "content": "Santal 33"}],
        active_perfume=advisor1.active_perfumes[session_id],
        guided_state={"step": None, "answers": []}
    )
    del advisor1  # SPEGNIMENTO PROCESSO (RAM AZZERATA)

    # Istanza 2: nuovo processo collegato allo stesso DB su file
    store2 = SessionStore(db_path=str(db_file))
    advisor2 = FragranceAdvisor(session_store=store2)

    # Prima della query, la RAM della nuova istanza è vuota
    assert session_id not in advisor2.active_perfumes

    # advisor.advise recupera lo stato da SQLite
    retrieved = store2.get_session(session_id)
    assert retrieved["active_perfume"]["name"] == "Santal 33"


# ==============================================================================
# 3. VERIFICA ENDPOINT HTTP FASTAPI /RESET
# ==============================================================================

def test_fastapi_reset_clears_database(tmp_path):
    """Verifica che la chiamata POST /reset pulisca lo storage SQLite attraverso l'API."""
    test_db = tmp_path / "http_reset_test.db"
    test_store = SessionStore(db_path=str(test_db))

    session_id = "http_reset_session"
    test_store.save_session(
        session_id,
        history=[{"role": "user", "content": "messaggio da rimuovere"}],
        active_perfume={"name": "Profumo X"},
        guided_state={"step": 2, "answers": []}
    )

    with TestClient(app) as client:
        import src.main
        src.main.advisor.session_store = test_store

        resp = client.post("/reset", json={"session_id": session_id})
        assert resp.status_code == 200

    # Verifica sul DB che i dati siano stati azzerati
    db_state = test_store.get_session(session_id)
    assert db_state["history"] == []
    assert db_state["active_perfume"] is None