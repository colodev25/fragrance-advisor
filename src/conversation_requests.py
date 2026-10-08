"""Coordina le operazioni di una sessione nel processo API corrente."""

from contextlib import contextmanager
from threading import Lock, RLock
try:
    from src.chat_budget import ChatUnavailable
except ModuleNotFoundError:
    from chat_budget import ChatUnavailable


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
    def hold(self, session_id: str, timeout=None):
        with self._guard:
            entry = self._entries.setdefault(session_id, {"lock": RLock(), "users": 0})
            # Include i thread in attesa: il lock non può essere sostituito mentre attendono.
            entry["users"] += 1
        acquired = False
        try:
            acquired = (entry["lock"].acquire() if timeout is None else
                        entry["lock"].acquire(timeout=max(0.0, timeout)))
            if not acquired:
                raise ChatUnavailable("chat_deadline_exceeded")
            yield
        finally:
            if acquired:
                entry["lock"].release()
            with self._guard:
                entry["users"] -= 1
                if entry["users"] == 0:
                    del self._entries[session_id]


session_coordinator = SessionCoordinator()
