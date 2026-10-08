"""Coordina le operazioni di una sessione nel processo API corrente."""

from contextlib import contextmanager
from threading import Lock, RLock


class RequestConflict(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SessionCoordinator:
    """Serializza solo la stessa sessione, senza trattenere lock inutilizzati."""

    def __init__(self):
        self._guard = Lock()
        self._entries = {}

    @contextmanager
    def hold(self, session_id: str):
        with self._guard:
            entry = self._entries.setdefault(session_id, {"lock": RLock(), "users": 0})
            # Include i thread in attesa: il lock non può essere sostituito mentre attendono.
            entry["users"] += 1
        try:
            with entry["lock"]:
                yield
        finally:
            with self._guard:
                entry["users"] -= 1
                if entry["users"] == 0:
                    del self._entries[session_id]


session_coordinator = SessionCoordinator()
