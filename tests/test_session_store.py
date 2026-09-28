import pytest
from src.session_store import SessionStore

@pytest.fixture
def temp_store(tmp_path):
    """Crea un'istanza di SessionStore su un database temporaneo isolato."""
    db_file = tmp_path / "test_sessions.db"
    return SessionStore(db_path=str(db_file))

def test_get_session_default(temp_store):
    state = temp_store.get_session("non_existent_session")
    assert state["history"] == []
    assert state["active_perfume"] is None
    assert state["guided_state"] == {"step": None, "answers": []}

def test_save_and_retrieve_session(temp_store):
    session_id = "user_abc_123"
    history = [
        {"role": "user", "content": "Cerco un profumo fresco"},
        {"role": "assistant", "content": "Ti consiglio Neroli Sauvage"}
    ]
    active_perfume = {"name": "Neroli Sauvage", "price": 210.0}
    guided_state = {"step": 2, "answers": ["🍋 Fresco o Agrumato"]}

    temp_store.save_session(session_id, history, active_perfume, guided_state)

    retrieved = temp_store.get_session(session_id)
    assert retrieved["history"] == history
    assert retrieved["active_perfume"] == active_perfume
    assert retrieved["guided_state"] == guided_state

def test_update_session_upsert(temp_store):
    session_id = "user_abc_123"
    temp_store.save_session(session_id, [], None, {"step": 1, "answers": []})

    # Aggiorna lo stato aggiungendo il profumo attivo
    updated_perfume = {"name": "Aventus", "price": 280.0}
    temp_store.save_session(session_id, [{"role": "user", "content": "ciao"}], updated_perfume, {"step": 2, "answers": ["Lui"]})

    retrieved = temp_store.get_session(session_id)
    assert len(retrieved["history"]) == 1
    assert retrieved["active_perfume"]["name"] == "Aventus"
    assert retrieved["guided_state"]["step"] == 2

def test_clear_session(temp_store):
    session_id = "user_to_clear"
    temp_store.save_session(session_id, [{"msg": 1}], {"name": "Test"}, {"step": 3, "answers": []})

    temp_store.clear_session(session_id)
    retrieved = temp_store.get_session(session_id)
    assert retrieved["history"] == []
    assert retrieved["active_perfume"] is None