"""
test_llm_resilience.py - Stress test per il wrapper di resilienza Groq
Valida: backoff temporale, failover 120B -> 20B, timeout, concorrenza e test live.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock
import httpx
import pytest
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, APITimeoutError, InternalServerError

load_dotenv()

from src.llm_resilience import ResilientGroqClient, PRIMARY_FREE_MODEL, FALLBACK_FREE_MODEL


@pytest.mark.parametrize("content,finish_reason", [("", "stop"), ("Risposta parziale", "length")])
def test_private_reasoning_and_truncated_answers_are_never_returned(content, finish_reason):
    mock_client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock(
        message=MagicMock(content=content, reasoning_content="Ragionamento interno privato"),
        finish_reason=finish_reason,
    )]
    mock_client.chat.completions.create.return_value = response
    resilient = ResilientGroqClient(mock_client, max_retries=0)
    assert resilient.create_completion([], graceful_fallback_text="Riprova") == "Riprova"


def test_invalid_selection_triggers_model_fallback():
    from src.advisor import parse_catalog_selection

    mock_client = MagicMock()
    def response(text):
        result = MagicMock()
        result.choices = [MagicMock(message=MagicMock(content=text), finish_reason="stop")]
        return result
    mock_client.chat.completions.create.side_effect = [
        response('{"selection":"PRODOTTO_99","reply":"Inventato"}'),
        response('{"selection":"PRODOTTO_1","reply":"Coerente"}'),
    ]
    resilient = ResilientGroqClient(mock_client, max_retries=0)
    result = resilient.create_completion(
        [], response_validator=lambda text: parse_catalog_selection(text, {"PRODOTTO_1": {}})
    )
    assert parse_catalog_selection(result, {"PRODOTTO_1": {}})["selection"] == "PRODOTTO_1"
    assert mock_client.chat.completions.create.call_args_list[1].kwargs["model"] == FALLBACK_FREE_MODEL


@pytest.mark.parametrize("text", [
    '[ID: PRODOTTO_1] Ottimo profumo',
    '{"selection":[],"reply":"Testo"}',
    '{"selection":"PRODOTTO_99","reply":"Testo"}',
    '{"selection":null,"reply":" "}',
    '{"selection":null,"reply":"Testo","extra":true}',
])
def test_catalog_selection_rejects_ambiguous_or_invalid_output(text):
    from src.advisor import parse_catalog_selection
    with pytest.raises(ValueError):
        parse_catalog_selection(text, {"PRODOTTO_1": {}})


def test_catalog_selection_allows_explicit_rejection():
    from src.advisor import parse_catalog_selection
    assert parse_catalog_selection('{"selection":null,"reply":"Nessun candidato adatto"}', {})["selection"] is None


@pytest.mark.parametrize("raw,expected_cards,clears_active", [
    ('{"selection":"PRODOTTO_1","reply":"Scelta coerente"}', 1, False),
    ('{"selection":null,"reply":"Nessuno adatto"}', 0, True),
    ('[ID: PRODOTTO_1] Testo non valido', 0, False),
])
def test_free_search_updates_state_only_for_valid_selection(raw, expected_cards, clears_active):
    from src.advisor import FragranceAdvisor
    advisor = FragranceAdvisor.__new__(FragranceAdvisor)
    previous = {"name": "Precedente", "family": "Legnosa"}
    candidate = {"name": "Nuovo", "price": 90, "document": "Note di rosa"}
    advisor.sessions = {"test": []}
    advisor.active_perfumes = {"test": previous}
    advisor.catalog_products = []
    advisor._find_mentioned_product = MagicMock(return_value=None)
    advisor._determine_intent = MagicMock(return_value="CAMBIA")
    advisor._extract_price_constraints = MagicMock(return_value=(None, None, "rosa"))
    advisor._has_explicit_olfactory_redirect = MagicMock(return_value=True)
    advisor._extract_target_notes = MagicMock(return_value=["rosa"])
    advisor._find_keyword_matches = MagicMock(return_value=[candidate])
    advisor.search_engine = MagicMock()
    advisor.search_engine.search.return_value = {"ids": [[]]}
    advisor.resilient_client = MagicMock()
    advisor.client = advisor._resilient_client.client
    advisor.resilient_client.create_completion.return_value = raw
    advisor._enrich_product_payload = MagicMock(side_effect=lambda product, **kwargs: product)
    if raw.startswith("[ID:"):
        from src.chat_budget import ChatUnavailable
        with pytest.raises(ChatUnavailable, match="llm_invalid_response"):
            advisor._handle_free_chat("Cerco rosa", "test", None)
        assert advisor.active_perfumes["test"] == previous
        assert advisor.sessions["test"] == []
        return
    result = advisor._handle_free_chat("Cerco rosa", "test", None)
    assert len(result["products"]) == expected_cards
    assert advisor.active_perfumes["test"] == (None if clears_active else candidate if expected_cards else previous)
    assert len(advisor.sessions["test"]) == 2


def test_history_limit_preserves_active_product_and_guided_preferences(tmp_path):
    from src.advisor import FragranceAdvisor, MAX_HISTORY_MESSAGES
    from src.session_store import SessionStore
    store = SessionStore(str(tmp_path / "history.db"))
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(60)]
    product = {"name": "Attivo"}
    store.save_session("test", history, product, {"step": None, "answers": ["Legnoso"]})
    advisor = FragranceAdvisor.__new__(FragranceAdvisor)
    advisor.session_store = store
    advisor.sessions, advisor.active_perfumes, advisor.guided_states = {}, {}, {}
    def free_chat(query, session_id, max_price):
        assert len(advisor.sessions[session_id]) == MAX_HISTORY_MESSAGES
        advisor.sessions[session_id].extend([{"role": "user", "content": query}, {"role": "assistant", "content": "Risposta"}])
        return {"reply": "Risposta"}
    advisor._handle_free_chat = free_chat
    advisor.advise("Una domanda", "test")
    saved = store.get_session("test")
    assert len(saved["history"]) == MAX_HISTORY_MESSAGES
    assert saved["history"][-1]["content"] == "Risposta"
    assert saved["active_perfume"] == product
    assert saved["guided_state"]["answers"] == ["Legnoso"]


def make_rate_limit_error(msg="Rate limit superato (TPM/RPM exceeded)"):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError(message=msg, response=response, body=None)


def test_no_retry_does_not_announce_a_sleep(monkeypatch, caplog):
    client = MagicMock()
    client.chat.completions.create.side_effect = make_rate_limit_error()
    sleep = MagicMock()
    monkeypatch.setattr("src.llm_resilience.time.sleep", sleep)
    ResilientGroqClient(client, max_retries=0).create_completion([])
    sleep.assert_not_called()
    assert "GROQ RATE_LIMIT" in caplog.text
    assert "attendo" not in caplog.text


def test_retry_after_is_respected(monkeypatch):
    client = MagicMock()
    error = make_rate_limit_error()
    error.response.headers["retry-after"] = "12"
    success = MagicMock()
    success.choices = [MagicMock(message=MagicMock(content="OK"), finish_reason="stop")]
    client.chat.completions.create.side_effect = [error, success]
    sleep = MagicMock()
    monkeypatch.setattr("src.llm_resilience.time.sleep", sleep)
    assert ResilientGroqClient(client, max_retries=1).create_completion([]) == "OK"
    sleep.assert_called_once_with(12.0)


def test_long_retry_after_defers_instead_of_retrying_early(monkeypatch):
    client = MagicMock()
    error = make_rate_limit_error()
    error.response.headers["retry-after"] = "3600"
    client.chat.completions.create.side_effect = error
    observer, sleep = MagicMock(), MagicMock()
    monkeypatch.setattr("src.llm_resilience.time.sleep", sleep)
    ResilientGroqClient(client, max_retries=1).create_completion([], fallback_model=PRIMARY_FREE_MODEL, failure_callback=observer)
    assert client.chat.completions.create.call_count == 1
    observer.assert_called_once_with("rate_limit", 3600.0)
    sleep.assert_not_called()


def test_timeout_has_distinct_diagnostic(caplog):
    client = MagicMock()
    client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
    observer = MagicMock()
    ResilientGroqClient(client, max_retries=0).create_completion([], fallback_model=PRIMARY_FREE_MODEL, failure_callback=observer)
    assert "GROQ TIMEOUT" in caplog.text
    observer.assert_called_once_with("timeout", None)


# ==============================================================================
# 1. BACKOFF TEMPORALE E AUTO-RIPRISTINO SUL MODELLO 120B
# ==============================================================================

def test_exponential_backoff_timing_and_recovery():
    mock_client = MagicMock()
    success_resp = MagicMock()
    success_resp.choices = [MagicMock(message=MagicMock(content="Accordo di rosa damascena e zafferano."))]

    # Tentativo 0: 429 -> attesa base_delay; Tentativo 1: Successo
    mock_client.chat.completions.create.side_effect = [
        make_rate_limit_error(),
        success_resp
    ]

    base_delay = 0.1
    resilient = ResilientGroqClient(mock_client, max_retries=2, base_delay=base_delay)

    start = time.perf_counter()
    reply = resilient.create_completion(messages=[{"role": "user", "content": "Note speziate"}])
    elapsed = time.perf_counter() - start

    call_args_list = mock_client.chat.completions.create.call_args_list
    assert reply == "Accordo di rosa damascena e zafferano."
    assert len(call_args_list) == 2
    assert call_args_list[0][1]["model"] == PRIMARY_FREE_MODEL
    assert call_args_list[1][1]["model"] == PRIMARY_FREE_MODEL
    assert elapsed >= (base_delay * 0.9), "Il backoff non ha rispettato il ritardo atteso."


# ==============================================================================
# 2. FAILOVER AL MODELLO 20B IN CASO DI TIMEOUT O RATE LIMIT PROLUNGATO
# ==============================================================================

def test_primary_failure_routes_to_secondary_model():
    mock_client = MagicMock()
    fallback_resp = MagicMock()
    fallback_resp.choices = [MagicMock(message=MagicMock(content="Risposta erogata dal motore rapido 20B."))]

    # 1 chiamata iniziale + 2 retry sul 120B falliti -> 1 chiamata sul 20B riuscita
    mock_client.chat.completions.create.side_effect = [
        make_rate_limit_error("120B saturo #1"),
        APITimeoutError(request=MagicMock()),
        make_rate_limit_error("120B saturo #3"),
        fallback_resp
    ]

    resilient = ResilientGroqClient(mock_client, max_retries=2, base_delay=0.01)
    reply = resilient.create_completion(messages=[{"role": "user", "content": "Consiglio sera"}])

    calls = mock_client.chat.completions.create.call_args_list
    assert reply == "Risposta erogata dal motore rapido 20B."
    assert len(calls) == 4
    for i in range(3):
        assert calls[i][1]["model"] == PRIMARY_FREE_MODEL
    assert calls[3][1]["model"] == FALLBACK_FREE_MODEL


# ==============================================================================
# 3. CONCORRENZA MULTI-THREAD SOTTO CARICO BURST
# ==============================================================================

def test_multithreaded_burst_traffic_resilience():
    call_count = 0

    def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        model = kwargs.get("model")
        # Simula instabilità: le chiamate dispari sul 120B falliscono
        if model == PRIMARY_FREE_MODEL and (call_count % 2 == 1):
            raise make_rate_limit_error("Burst rate-limit simulato")
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=f"OK da {model}"))]
        return resp

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_create

    resilient = ResilientGroqClient(mock_client, max_retries=1, base_delay=0.01)
    workers = 10
    results = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(resilient.create_completion, [{"role": "user", "content": f"Query {i}"}])
            for i in range(workers)
        ]
        for f in as_completed(futures):
            results.append(f.result())

    assert len(results) == workers
    assert all("OK da openai/gpt-oss-" in r for r in results)


# ==============================================================================
# 4. BLACKOUT TOTALE DELLE API (GRACEFUL DEGRADATION)
# ==============================================================================

def test_total_api_failure_graceful_degradation():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = InternalServerError(
        message="Groq Service Unavailable", response=MagicMock(status_code=503), body=None
    )

    resilient = ResilientGroqClient(mock_client, max_retries=1, base_delay=0.01)
    fallback_text = "I nostri profumieri stanno evadendo molte richieste."

    reply = resilient.create_completion(
        messages=[{"role": "user", "content": "Cerco ambra"}],
        graceful_fallback_text=fallback_text
    )

    assert reply == fallback_text


# ==============================================================================
# 5. TEST LIVE SU GROQ CON I MODELLI EFFETTIVI A COSTO 0€
# ==============================================================================

@pytest.mark.e2e
def test_live_execution_on_active_models():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY non presente in .env.")

    real_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    resilient = ResilientGroqClient(real_client, max_retries=1, base_delay=0.5)

    # Verifica modello Primario 120B con token sufficienti per il reasoning
    reply_120b = resilient.create_completion(
        messages=[{"role": "user", "content": "Definisci in una sola frase elegante il concetto di sillage."}],
        primary_model=PRIMARY_FREE_MODEL,
        max_tokens=250
    )
    assert len(reply_120b.strip()) > 15
    assert "Maître Parfumeur" not in reply_120b

    # Verifica modello Secondario 20B
    reply_20b = resilient.create_completion(
        messages=[{"role": "user", "content": "Definisci in una sola frase elegante il concetto di sillage."}],
        primary_model=FALLBACK_FREE_MODEL,
        fallback_model=FALLBACK_FREE_MODEL,
        max_tokens=250
    )
    assert len(reply_20b.strip()) > 15
    assert "Maître Parfumeur" not in reply_20b
