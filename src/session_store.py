"""SQLite state, atomic request receipts and 24-hour inactivity expiry."""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
try:
    from src.conversation_requests import RequestConflict, session_coordinator
    from src.chat_budget import ChatUnavailable
except ModuleNotFoundError:
    from conversation_requests import RequestConflict, session_coordinator
    from chat_budget import ChatUnavailable

MAX_STORED_RESPONSES = 100
SESSION_TTL_SECONDS = 24 * 60 * 60
CLEANUP_BATCH_SIZE = 100


class SessionStore:
    def __init__(self, db_path: Optional[str] = None):
        selected_path = db_path or os.getenv("SESSIONS_DB_PATH") or (
            Path(__file__).resolve().parent.parent / "data" / "sessions.db")
        if str(selected_path) == ":memory:":
            raise ValueError("SessionStore richiede un database SQLite su file; "
                             "usa un file temporaneo per i test, non ':memory:'.")
        self.db_path = Path(selected_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self, timeout=15.0):
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY, history TEXT NOT NULL, active_perfume TEXT,
                    guided_state TEXT NOT NULL, updated_at TIMESTAMP NOT NULL,
                    session_token TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0,
                    expires_at REAL NOT NULL DEFAULT 0
                );
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
            for name, declaration in (
                ("session_token", "TEXT NOT NULL DEFAULT ''"),
                ("revision", "INTEGER NOT NULL DEFAULT 0"),
                ("expires_at", "REAL NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {declaration}")
            # Legacy dates without a timezone are interpreted as UTC.
            for row in conn.execute("SELECT session_id, updated_at FROM sessions WHERE session_token = ''"):
                try:
                    updated = datetime.fromisoformat(row["updated_at"])
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    expiry = updated.timestamp() + SESSION_TTL_SECONDS
                except (ValueError, TypeError, OverflowError):
                    expiry = 0
                conn.execute("UPDATE sessions SET session_token = ?, expires_at = ? WHERE session_id = ?",
                             (uuid.uuid4().hex, expiry, row["session_id"]))
            conn.execute("CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_requests (
                    session_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    response TEXT, created_at TEXT NOT NULL, PRIMARY KEY (session_id, request_id)
                );
            """)

    @staticmethod
    def _context(row):
        return {"token": row["session_token"], "revision": row["revision"],
                "expires_at": int(row["expires_at"] * 1000)}

    def get_request_response(self, session_id: str, request_id: str, fingerprint: str):
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

    def get_session(self, session_id: str, include_expired=False) -> Dict[str, Any]:
        default = {"history": [], "active_perfume": None,
                   "guided_state": {"step": None, "answers": []}, "session_context": None}
        if not session_id:
            return default
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None or (not include_expired and row["expires_at"] <= time.time()):
            return default
        def decode(key, fallback, expected):
            try:
                result = json.loads(row[key]) if row[key] else fallback
                return result if isinstance(result, expected) else fallback
            except (ValueError, TypeError):
                return fallback
        return {
            "history": decode("history", [], list),
            "active_perfume": decode("active_perfume", None, dict),
            "guided_state": decode("guided_state", {"step": None, "answers": []}, dict),
            "session_context": self._context(row),
        }

    def save_session(
        self, session_id: str, history: List[Dict[str, Any]],
        active_perfume: Optional[Dict[str, Any]], guided_state: Dict[str, Any],
        request_id: Optional[str] = None, fingerprint: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None, include_session_context=False,
    ):
        if not session_id:
            return None
        if request_id is not None and (fingerprint is None or response is None):
            raise ValueError("Una richiesta identificata richiede fingerprint e risposta.")
        timestamp = time.time()
        now = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        expiry = timestamp + SESSION_TTL_SECONDS
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT session_token, revision, expires_at FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            alive = previous is not None and previous["expires_at"] > timestamp
            token = previous["session_token"] if alive else uuid.uuid4().hex
            revision = previous["revision"] + 1 if alive else 1
            context = {"token": token, "revision": revision, "expires_at": int(expiry * 1000)}
            if previous is not None and not alive:
                conn.execute("DELETE FROM chat_requests WHERE session_id = ?", (session_id,))
            conn.execute("""
                INSERT INTO sessions
                (session_id, history, active_perfume, guided_state, updated_at, session_token, revision, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    history = excluded.history, active_perfume = excluded.active_perfume,
                    guided_state = excluded.guided_state, updated_at = excluded.updated_at,
                    session_token = excluded.session_token, revision = excluded.revision,
                    expires_at = excluded.expires_at
            """, (session_id, json.dumps(history, ensure_ascii=False),
                  json.dumps(active_perfume, ensure_ascii=False) if active_perfume else None,
                  json.dumps(guided_state, ensure_ascii=False), now, token, revision, expiry))
            if request_id is not None:
                saved_response = {**response, "session_context": context} if include_session_context else response
                conn.execute(
                    "INSERT INTO chat_requests (session_id, request_id, fingerprint, response, created_at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, request_id, fingerprint, json.dumps(saved_response, ensure_ascii=False), now),
                )
                conn.execute("""
                    UPDATE chat_requests SET response = NULL
                    WHERE session_id = ? AND response IS NOT NULL AND rowid NOT IN (
                        SELECT rowid FROM chat_requests WHERE session_id = ?
                        AND response IS NOT NULL ORDER BY rowid DESC LIMIT ?
                    )
                """, (session_id, session_id, MAX_STORED_RESPONSES))
        return context

    def clear_session(self, session_id: str):
        if not session_id:
            return
        with self._get_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM chat_requests WHERE session_id = ?", (session_id,))

    def cleanup_old_sessions(self, limit=CLEANUP_BATCH_SIZE):
        """Skip busy conversations and recheck expiry under their session lock."""
        with self._get_connection(timeout=1.0) as conn:
            candidates = conn.execute(
                "SELECT session_id FROM sessions WHERE expires_at <= ? ORDER BY expires_at LIMIT ?",
                (time.time(), limit),
            ).fetchall()
        removed = 0
        for row in candidates:
            sid = row["session_id"]
            try:
                with session_coordinator.hold(sid, timeout=0):
                    with self._get_connection(timeout=1.0) as conn:
                        deleted = conn.execute(
                            "DELETE FROM sessions WHERE session_id = ? AND expires_at <= ?", (sid, time.time())
                        ).rowcount
                        if deleted:
                            conn.execute("DELETE FROM chat_requests WHERE session_id = ?", (sid,))
                            removed += deleted
            except ChatUnavailable:
                continue
        return removed
