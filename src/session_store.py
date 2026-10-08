"""
session_store.py - Gestore della persistenza delle sessioni su SQLite
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from src.conversation_requests import RequestConflict
except ModuleNotFoundError:
    from conversation_requests import RequestConflict

MAX_STORED_RESPONSES = 100


class SessionStore:
    """Gestore della persistenza delle sessioni e dello stato conversazionale su SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            env_path = os.getenv("SESSIONS_DB_PATH")
            if env_path:
                self.db_path = Path(env_path)
            else:
                base_dir = Path(__file__).resolve().parent.parent
                self.db_path = base_dir / "data" / "sessions.db"

        # Assicura che la directory genitore esista sempre
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Crea una connessione SQLite sicura con timeout e dizionario."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Inizializza la tabella sessions con modalità WAL per la concorrenza multi-thread."""
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    history TEXT NOT NULL,
                    active_perfume TEXT,
                    guided_state TEXT NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );
            """)
            conn.commit()

            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_requests (
                    session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    response TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, request_id)
                );
            """)
            conn.commit()

    def get_request_response(self, session_id: str, request_id: str, fingerprint: str):
        """Restituisce un risultato concluso; un ID già usato non viene rielaborato."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT fingerprint, response FROM chat_requests WHERE session_id = ? AND request_id = ?",
                (session_id, request_id),
            ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint:
            raise RequestConflict("request_id_conflict", "Questo identificativo appartiene a un messaggio diverso.")
        if row["response"] is None:
            raise RequestConflict("request_result_expired", "Il risultato di questo messaggio non è più disponibile. Invia un nuovo messaggio.")
        return json.loads(row["response"])

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Recupera lo stato della sessione. Se inesistente, restituisce lo stato vuoto standard."""
        default_state = {
            "history": [],
            "active_perfume": None,
            "guided_state": {"step": None, "answers": []}
        }
        if not session_id:
            return default_state

        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT history, active_perfume, guided_state FROM sessions WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            if not row:
                return default_state

            try:
                history = json.loads(row["history"])
            except Exception:
                history = []

            try:
                active_perfume = json.loads(row["active_perfume"]) if row["active_perfume"] else None
            except Exception:
                active_perfume = None

            try:
                guided_state = json.loads(row["guided_state"])
            except Exception:
                guided_state = {"step": None, "answers": []}

            return {
                "history": history,
                "active_perfume": active_perfume,
                "guided_state": guided_state
            }

    def save_session(
        self,
        session_id: str,
        history: List[Dict[str, Any]],
        active_perfume: Optional[Dict[str, Any]],
        guided_state: Dict[str, Any],
        request_id: Optional[str] = None,
        fingerprint: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
    ):
        """Salva o aggiorna lo stato completo della sessione con operazione atomica."""
        if not session_id:
            return

        now = datetime.now(timezone.utc).isoformat()
        history_json = json.dumps(history, ensure_ascii=False)
        perfume_json = json.dumps(active_perfume, ensure_ascii=False) if active_perfume else None
        guided_json = json.dumps(guided_state, ensure_ascii=False)
        if request_id is not None and (fingerprint is None or response is None):
            raise ValueError("Una richiesta identificata richiede fingerprint e risposta.")
        response_json = json.dumps(response, ensure_ascii=False) if request_id is not None else None

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO sessions (session_id, history, active_perfume, guided_state, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    history = excluded.history,
                    active_perfume = excluded.active_perfume,
                    guided_state = excluded.guided_state,
                    updated_at = excluded.updated_at;
            """, (session_id, history_json, perfume_json, guided_json, now))
            if request_id is not None:
                conn.execute(
                    "INSERT INTO chat_requests (session_id, request_id, fingerprint, response, created_at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, request_id, fingerprint, response_json, now),
                )
                # Mantiene 100 risposte complete. I precedenti ID restano riconosciuti,
                # evitando nuove chiamate LLM quando il risultato è stato scartato.
                conn.execute("""
                    UPDATE chat_requests SET response = NULL
                    WHERE session_id = ? AND response IS NOT NULL AND rowid NOT IN (
                        SELECT rowid FROM chat_requests WHERE session_id = ?
                        AND response IS NOT NULL ORDER BY rowid DESC LIMIT ?
                    )
                """, (session_id, session_id, MAX_STORED_RESPONSES))
            conn.commit()

    def clear_session(self, session_id: str):
        """Elimina fisicamente la sessione (reset della conversazione)."""
        if not session_id:
            return
        with self._get_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM chat_requests WHERE session_id = ?", (session_id,))
            conn.commit()

    def cleanup_old_sessions(self, days: int = 30):
        """Rimuove le sessioni non aggiornate da oltre N giorni."""
        with self._get_connection() as conn:
            conn.execute("""
                DELETE FROM chat_requests WHERE session_id IN (
                    SELECT session_id FROM sessions WHERE updated_at < datetime('now', ?)
                )
            """, (f"-{days} days",))
            conn.execute(
                "DELETE FROM sessions WHERE updated_at < datetime('now', ?)",
                (f"-{days} days",)
            )
            conn.commit()
