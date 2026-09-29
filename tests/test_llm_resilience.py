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


def make_rate_limit_error(msg="Rate limit superato (TPM/RPM exceeded)"):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError(message=msg, response=response, body=None)


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