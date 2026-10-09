"""R01: access checks use the real API and store; no implicit test credentials."""
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import src.main as api
from src.conversation_requests import SessionAccessError
from src.session_store import SessionStore
from tests.test_conversation_requests import make_advisor

KEY = 'b' * 64
OTHER = 'c' * 64


@pytest.fixture
def protected(tmp_path, monkeypatch):
    advisor = make_advisor(SessionStore(str(tmp_path / 'protected.db')))
    monkeypatch.setattr(api, 'advisor', advisor)
    api.rate_limiter.reset()
    return advisor, TestClient(api.app)


@pytest.mark.parametrize('endpoint', ['/chat', '/reset'])
@pytest.mark.parametrize('credential', [None, '', 'x' * 64, 123, 'b' * 63, 'b' * 65])
def test_missing_or_invalid_credential_is_rejected(protected, endpoint, credential):
    advisor, client = protected
    payload = {'session_id': 'customer', 'message': 'iris'}
    if credential is not None:
        payload['session_key'] = credential
    response = client.post(endpoint, json=payload)
    assert response.status_code == 422
    advisor._handle_free_chat.assert_not_called()


@pytest.mark.parametrize('endpoint', ['/chat', '/reset'])
def test_known_id_and_context_do_not_grant_access(protected, endpoint):
    advisor, client = protected
    payload = {'session_id': 'customer', 'session_key': KEY, 'message': 'iris', 'request_id': 'req_first'}
    first = client.post('/chat', json=payload).json()
    before = advisor.session_store.get_session('customer')
    for context in [None, first['session_context']]:
        denied = client.post(endpoint, json={**payload, 'session_key': OTHER, 'session_context': context})
        assert denied.status_code == 403
        assert denied.json()['error']['code'] == 'session_access_denied'
        assert KEY not in denied.text and OTHER not in denied.text
    assert advisor.session_store.get_session('customer') == before
    assert advisor._handle_free_chat.call_count == 1


def test_context_cannot_be_omitted_to_continue_or_replay(protected):
    advisor, client = protected
    first_payload = {'session_id': 'customer', 'session_key': KEY, 'message': 'iris', 'request_id': 'req_first'}
    first = client.post('/chat', json=first_payload)
    assert first.status_code == 200
    # First response lost: the original authenticated request recovers it.
    assert client.post('/chat', json=first_payload).json() == first.json()
    second_payload = {**first_payload, 'message': 'rosa', 'request_id': 'req_second'}
    rejected = client.post('/chat', json=second_payload)
    assert rejected.status_code == 409
    assert rejected.json()['error']['code'] == 'session_context_required'
    second_payload['session_context'] = first.json()['session_context']
    second = client.post('/chat', json=second_payload)
    assert second.status_code == 200
    assert client.post('/chat', json=second_payload).json() == second.json()
    assert client.post('/chat', json=first_payload).json()['error']['code'] == 'session_out_of_sync'
    omitted = {k: v for k, v in second_payload.items() if k != 'session_context'}
    assert client.post('/chat', json=omitted).json()['error']['code'] == 'request_id_conflict'
    assert advisor._handle_free_chat.call_count == 2


def test_credential_is_hashed_and_never_in_response_or_receipt(protected):
    advisor, client = protected
    response = client.post('/chat', json={'message': 'iris', 'session_id': 'customer', 'session_key': KEY, 'request_id': 'req_first'})
    assert response.status_code == 200
    assert KEY not in response.text and 'session_key' not in response.text
    with advisor.session_store._get_connection() as conn:
        row = conn.execute('SELECT * FROM sessions').fetchone()
        assert row['credential_hash'] == hashlib.sha256(KEY.encode()).hexdigest()
        assert KEY not in str(tuple(row))
        assert KEY not in str(tuple(conn.execute('SELECT * FROM chat_requests').fetchone()))


def test_failed_first_call_cannot_be_claimed_by_another_client(protected):
    advisor, client = protected
    original = advisor._handle_free_chat.side_effect
    advisor._handle_free_chat.side_effect = RuntimeError('offline outage')
    payload = {'message': 'iris', 'session_id': 'customer', 'session_key': KEY, 'request_id': 'req_first'}
    assert client.post('/chat', json=payload).status_code == 503
    assert client.post('/chat', json={**payload, 'session_key': OTHER}).status_code == 403
    advisor._handle_free_chat.side_effect = original
    assert client.post('/chat', json=payload).status_code == 200


def test_atomic_claim_has_exactly_one_owner(protected):
    advisor, _ = protected
    def claim(key):
        try:
            advisor.session_store.authorize_session('racing', key, allow_create=True)
            return key
        except SessionAccessError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        owners = list(pool.map(claim, [KEY, OTHER]))
    assert len([owner for owner in owners if owner]) == 1


def test_legacy_session_is_never_adopted(protected):
    advisor, client = protected
    advisor.session_store.save_session('legacy', [{'role': 'user', 'content': 'private'}], None, {})
    before = advisor.session_store.get_session('legacy')
    for endpoint in ['/chat', '/reset']:
        response = client.post(endpoint, json={'message': 'iris', 'session_id': 'legacy', 'session_key': KEY})
        assert response.status_code == 409
        assert response.json()['error']['code'] == 'session_migration_required'
    assert advisor.session_store.get_session('legacy') == before


def test_direct_advisor_cannot_bypass_access(protected):
    advisor, _ = protected
    with pytest.raises(SessionAccessError):
        advisor.advise('iris', 'customer')
    advisor.advise('iris', 'customer', session_key=KEY)
    with pytest.raises(SessionAccessError):
        advisor.reset_session('customer')
    advisor.reset_session('customer', session_key=KEY)
    assert advisor.session_store.get_session('customer')['history'] == []


def test_reset_does_not_report_success_when_service_is_unavailable(protected, monkeypatch):
    _, client = protected
    monkeypatch.setattr(api, 'advisor', None)
    response = client.post('/reset', json={'session_id': 'customer', 'session_key': KEY})
    assert response.status_code == 503


def test_invalid_first_credential_cannot_create_a_claim(protected):
    advisor, _ = protected
    with pytest.raises(SessionAccessError):
        advisor.advise('iris', 'customer', session_key='invalid')
    with advisor.session_store._get_connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
