import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from src.session_store import SessionStore
from src.advisor import FragranceAdvisor
from src.main import app


# ==============================================================================
# FIXTURE DI SUPPORTO
# ==============================================================================

@pytest.fixture
def temp_store(tmp_path):
    """Fornisce un'istanza di SessionStore operante su un DB SQLite temporaneo su disco."""
    db_file = tmp_path / "unit_test_sessions.db"
    return SessionStore(db_path=str(db_file))


@pytest.fixture
def clean_mock_advisor(tmp_path):
    """Fornisce un'istanza isolata di FragranceAdvisor con client Groq e ChromaDB mockati
    per test di logica veloci e deterministici."""
    db_file = tmp_path / "mock_test_sessions.db"
    store = SessionStore(db_path=str(db_file))
    advisor = FragranceAdvisor(session_store=store)
    advisor.client = MagicMock()
    advisor.search_engine = MagicMock()
    return advisor, store, db_file


# ==============================================================================
# LIVELLO 1: UNIT TEST BASSO LIVELLO (SQLITE & EDGE CASES)
# ==============================================================================

def test_store_default_session(temp_store):
    """Verifica che una sessione mai registrata restituisca la struttura di default pulita."""
    state = temp_store.get_session("sessione_inesistente")
    assert state["history"] == []
    assert state["active_perfume"] is None
    assert state["guided_state"] == {"step": None, "answers": []}


def test_store_save_and_retrieve(temp_store):
    """Verifica il salvataggio e il recupero conforme di cronologia, profumo e quiz."""
    session_id = "user_persisted_01"
    history = [
        {"role": "user", "content": "Cerco un profumo fresco"},
        {"role": "assistant", "content": "Ti consiglio Neroli Sauvage"}
    ]
    active_perfume = {
        "name": "Neroli Sauvage",
        "brand": "Creed",
        "price": 210.0,
        "family": "Agrumata"
    }
    guided_state = {"step": 2, "answers": ["🍋 Fresco o Agrumato"]}

    temp_store.save_session(session_id, history, active_perfume, guided_state)

    retrieved = temp_store.get_session(session_id)
    assert retrieved["history"] == history
    assert retrieved["active_perfume"] == active_perfume
    assert retrieved["guided_state"] == guided_state


def test_store_upsert_overwrite(temp_store):
    """Verifica che scritture successive sullo stesso ID aggiornino il record esistente (UPSERT)."""
    session_id = "user_upsert_test"
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
    assert len(retrieved["guided_state"]["answers"]) == 2


def test_store_clear_session(temp_store):
    """Verifica l'eliminazione fisica della sessione da SQLite."""
    session_id = "user_to_delete"
    temp_store.save_session(session_id, [{"m": 1}], {"name": "Test"}, {"step": 3, "answers": []})

    temp_store.clear_session(session_id)
    retrieved = temp_store.get_session(session_id)
    assert retrieved["history"] == []
    assert retrieved["active_perfume"] is None
    assert retrieved["guided_state"]["step"] is None


def test_store_cleanup_old_sessions(temp_store):
    """Verifica che cleanup_old_sessions elimini solo i record che superano la data limite."""
    # Inserimento manuale di un record obsoleto (35 giorni fa) e uno recente (ieri)
    old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    recent_date = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()

    with temp_store._get_connection() as conn:
        conn.execute("""
            INSERT INTO sessions (session_id, history, active_perfume, guided_state, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, ("sess_old", "[]", None, "{}", old_date))
        conn.execute("""
            INSERT INTO sessions (session_id, history, active_perfume, guided_state, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, ("sess_recent", "[]", None, "{}", recent_date))
        conn.commit()

    temp_store.cleanup_old_sessions(days=30)

    assert temp_store.get_session("sess_old")["history"] == []
    assert temp_store.get_session("sess_recent") != {"history": [], "active_perfume": None, "guided_state": {"step": None, "answers": []}}


def test_store_corrupted_json_resilience(temp_store):
    """Verifica la robustezza contro dati corrotti nel DB (fallback a strutture vuote senza crash)."""
    with temp_store._get_connection() as conn:
        conn.execute("""
            INSERT INTO sessions (session_id, history, active_perfume, guided_state, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
        """, ("sess_corrupted", "{MALFORMED_JSON", "{INVALID_JSON", "{BROKEN_GUIDED"))
        conn.commit()

    state = temp_store.get_session("sess_corrupted")
    assert state["history"] == []
    assert state["active_perfume"] is None
    assert state["guided_state"] == {"step": None, "answers": []}


# ==============================================================================
# LIVELLO 2: TEST DI INTEGRAZIONE ADVISOR (LOGICA DI STATO E ISOLAMENTO)
# ==============================================================================

def test_advisor_session_isolation(clean_mock_advisor):
    """Verifica che utenti simultanei abbiano stati, cronologie e profumi attivi isolati."""
    advisor, store, _ = clean_mock_advisor

    # Alice imposta un profumo
    store.save_session(
        session_id="alice",
        history=[{"role": "user", "content": "Cerco vaniglia"}],
        active_perfume={"name": "Vanilla Diorama", "price": 240.0},
        guided_state={"step": None, "answers": []}
    )

    # Bob si trova allo Step 2 del quiz guidato
    store.save_session(
        session_id="bob",
        history=[{"role": "user", "content": "guidami"}],
        active_perfume=None,
        guided_state={"step": 2, "answers": ["🍋 Fresco o Agrumato"]}
    )

    # Verifica recupero Alice
    state_alice = store.get_session("alice")
    assert state_alice["active_perfume"]["name"] == "Vanilla Diorama"
    assert state_alice["guided_state"]["step"] is None

    # Verifica recupero Bob
    state_bob = store.get_session("bob")
    assert state_bob["active_perfume"] is None
    assert state_bob["guided_state"]["step"] == 2
    assert "🍋 Fresco o Agrumato" in state_bob["guided_state"]["answers"]


def test_advisor_mode_switching(clean_mock_advisor):
    """Verifica che il passaggio da quiz guidato a chat libera resetti correttamente lo step su DB."""
    advisor, store, _ = clean_mock_advisor
    session_id = "switch_user"

    # 1. Avvio quiz
    res_g = advisor.advise("🎯 Guidami nella scelta", session_id=session_id)
    assert res_g["step"] == 1
    assert store.get_session(session_id)["guided_state"]["step"] == 1

    # 2. L'utente decide di passare a domanda libera
    res_f = advisor.advise("💬 Fai una domanda libera", session_id=session_id)
    assert res_f["step"] is None
    assert res_f["mode"] == "free"
    assert store.get_session(session_id)["guided_state"]["step"] is None


def test_advisor_reset_session_both_memory_and_db(clean_mock_advisor):
    """Verifica che reset_session elimini le informazioni sia dalla RAM che dalla tabella SQLite."""
    advisor, store, _ = clean_mock_advisor
    session_id = "purge_user"

    advisor.sessions[session_id] = [{"role": "user", "content": "ciao"}]
    advisor.active_perfumes[session_id] = {"name": "Test Perfume"}
    advisor.guided_states[session_id] = {"step": 2, "answers": ["🍋 Fresco o Agrumato"]}
    store.save_session(
        session_id,
        advisor.sessions[session_id],
        advisor.active_perfumes[session_id],
        advisor.guided_states[session_id]
    )

    advisor.reset_session(session_id)

    # Controllo cache in memoria
    assert session_id not in advisor.sessions
    assert session_id not in advisor.active_perfumes
    assert session_id not in advisor.guided_states

    # Controllo persistenza su SQLite
    db_state = store.get_session(session_id)
    assert db_state["history"] == []
    assert db_state["active_perfume"] is None
    assert db_state["guided_state"]["step"] is None


# ==============================================================================
# LIVELLO 3: TEST END-TO-END LIVE (GROQ + CHROMADB + SQLITE REALI)
# ==============================================================================

@pytest.mark.e2e
def test_e2e_guided_flow_across_server_restarts(tmp_path):
    """TEST LIVE: Percorso guidato completo in cui il server viene simulato RIAVVIATO
    a ogni step (azzeramento totale della memoria RAM). Groq e ChromaDB generano il finale."""
    db_file = tmp_path / "e2e_guided_flow.db"
    session_id = "live_guided_user"

    # --- Step 1: Istanza 1 ---
    store1 = SessionStore(db_path=str(db_file))
    advisor1 = FragranceAdvisor(session_store=store1)
    res1 = advisor1.advise("🎯 Guidami nella scelta", session_id=session_id)
    assert res1["step"] == 1
    del advisor1  # RIAVVIO SERVER

    # --- Step 2: Istanza 2 ---
    store2 = SessionStore(db_path=str(db_file))
    advisor2 = FragranceAdvisor(session_store=store2)
    res2 = advisor2.advise("🍋 Fresco o Agrumato", session_id=session_id)
    assert res2["step"] == 2
    del advisor2  # RIAVVIO SERVER

    # --- Step 3: Istanza 3 ---
    store3 = SessionStore(db_path=str(db_file))
    advisor3 = FragranceAdvisor(session_store=store3)
    res3 = advisor3.advise("Per Lui", session_id=session_id)
    assert res3["step"] == 3
    del advisor3  # RIAVVIO SERVER

    # --- Step 4: Istanza 4 ---
    store4 = SessionStore(db_path=str(db_file))
    advisor4 = FragranceAdvisor(session_store=store4)
    res4 = advisor4.advise("Tutti i giorni / Ufficio", session_id=session_id)
    assert res4["step"] == 4
    del advisor4  # RIAVVIO SERVER

    # --- Raccomandazione Finale: Istanza 5 (ChromaDB + Groq) ---
    time.sleep(1.2)  # Rispetto dei rate limits Groq
    store5 = SessionStore(db_path=str(db_file))
    advisor5 = FragranceAdvisor(session_store=store5)
    res_final = advisor5.advise("Nessun limite di budget", session_id=session_id)

    # Validazione output finale
    assert res_final["step"] is None
    assert len(res_final["products"]) > 0
    assert len(res_final["reply"]) > 20
    assert advisor5.active_perfumes[session_id] is not None

    # Controllo che il profumo attivo finale sia persistito su SQLite
    persisted = store5.get_session(session_id)
    assert persisted["active_perfume"] is not None
    assert persisted["active_perfume"]["name"] == advisor5.active_perfumes[session_id]["name"]


@pytest.mark.e2e
def test_e2e_free_chat_entity_and_followup_across_restarts(tmp_path):
    """TEST LIVE: In chat libera l'utente nomina una fragranza a catalogo.
    Il server si riavvia. L'utente pone un follow-up (VALUTA) e il nuovo advisor
    risponde conoscendo il profumo salvato su disco."""
    db_file = tmp_path / "e2e_free_chat.db"
    session_id = "live_free_chat_user"

    # --- Fase 1: Riconoscimento entità su Istanza 1 ---
    store1 = SessionStore(db_path=str(db_file))
    advisor1 = FragranceAdvisor(session_store=store1)
    res1 = advisor1.advise("Parlami di Aventus di Creed", session_id=session_id)

    assert len(res1["products"]) == 1
    selected_name = res1["products"][0]["name"]
    assert "aventus" in selected_name.lower()
    assert advisor1.active_perfumes[session_id] is not None
    del advisor1  # SPEGNIMENTO TOTALE DEL SERVER (RAM AZZERATA)

    # --- Fase 2: Riavvio server su Istanza 2 ---
    time.sleep(1.2)
    store2 = SessionStore(db_path=str(db_file))
    advisor2 = FragranceAdvisor(session_store=store2)

    # La RAM della nuova istanza non contiene la sessione finché non legge da SQLite
    assert session_id not in advisor2.active_perfumes

    # Follow-up di valutazione (VALUTA)
    res2 = advisor2.advise("Quali sono le sue note olfattive principali?", session_id=session_id)

    # Verifiche
    assert advisor2.active_perfumes[session_id] is not None
    assert advisor2.active_perfumes[session_id]["name"] == selected_name
    assert len(res2["reply"]) > 15
    assert len(res2["products"]) == 0  # Follow-up senza card duplicate


@pytest.mark.e2e
def test_e2e_free_chat_alternative_switch_across_restarts(tmp_path):
    """TEST LIVE: L'utente ha un profumo attivo. Il server si riavvia.
    L'utente chiede un'alternativa più economica. Il nuovo advisor attiva il router
    CAMBIA ed esegue la ricerca ibrida con vincolo di budget."""
    db_file = tmp_path / "e2e_alternative_switch.db"
    session_id = "live_switch_user"

    # Istanza 1: imposta profumo di partenza
    store1 = SessionStore(db_path=str(db_file))
    advisor1 = FragranceAdvisor(session_store=store1)
    res1 = advisor1.advise("Consigliami un profumo legnoso", session_id=session_id)
    assert len(res1["products"]) > 0
    first_perfume = advisor1.active_perfumes[session_id]
    del advisor1  # RIAVVIO SERVER

    # Istanza 2: richiesta alternativa
    time.sleep(1.2)
    store2 = SessionStore(db_path=str(db_file))
    advisor2 = FragranceAdvisor(session_store=store2)

    res2 = advisor2.advise("Vorrei un'alternativa più economica sotto i 150 euro", session_id=session_id)

    # Verifiche
    assert len(res2["products"]) > 0
    new_perfume = advisor2.active_perfumes[session_id]
    assert new_perfume is not None
    assert new_perfume["price"] <= 150.0

    # Verifica persistenza del nuovo profumo attivo
    persisted = store2.get_session(session_id)
    assert persisted["active_perfume"]["name"] == new_perfume["name"]


# ==============================================================================
# LIVELLO 4: TEST END-TO-END FASTAPI HTTP (TESTCLIENT + PERSISTENZA)
# ==============================================================================

@pytest.mark.e2e
def test_e2e_fastapi_http_endpoint_with_persistence(tmp_path):
    """TEST LIVE HTTP: Verifica che l'endpoint FastAPI /chat gestisca le chiamate
    del widget frontend, serializzando correttamente il JSON e mantenendo la sessione."""
    from src.main import advisor as main_advisor

    # Colleghiamo temporaneamente l'advisor di FastAPI al database temporaneo isolato
    test_db = tmp_path / "fastapi_e2e.db"
    test_store = SessionStore(db_path=str(test_db))
    main_advisor.session_store = test_store

    client = TestClient(app)
    session_id = f"http_test_{int(time.time())}"

    # 1. Chiamata HTTP Step 1
    resp1 = client.post("/chat", json={"message": "🎯 Guidami nella scelta", "session_id": session_id})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["step"] == 1
    assert "🍋 Fresco o Agrumato" in data1["options"]

    # 2. Chiamata HTTP Step 2
    resp2 = client.post("/chat", json={"message": "🍋 Fresco o Agrumato", "session_id": session_id})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["step"] == 2
    assert "Per Lui" in data2["options"]

    # 3. Controllo diretto su SQLite: lo stato deve essere salvato
    persisted = test_store.get_session(session_id)
    assert persisted["guided_state"]["step"] == 2
    assert persisted["guided_state"]["answers"] == ["🍋 Fresco o Agrumato"]