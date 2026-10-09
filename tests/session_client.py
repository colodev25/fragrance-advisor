"""Authenticated sequential client for recommendation scenarios, not access tests."""
import hashlib


def client_advise(advisor, user_query, session_id, **kwargs):
    key = hashlib.sha256(('test-client:' + session_id).encode()).hexdigest()
    if not hasattr(advisor, 'session_store') or advisor.session_store is None:
        from src.session_store import SessionStore
        advisor.session_store = SessionStore()
    state = advisor.session_store.get_session(session_id)
    kwargs.setdefault('session_key', key)
    kwargs.setdefault('session_context', state['session_context'])
    return advisor.advise(user_query, session_id, **kwargs)
