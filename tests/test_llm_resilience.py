import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock
import httpx
import pytest
from openai import OpenAI, RateLimitError, APITimeoutError
from dotenv import load_dotenv

# Carica le variabili da .env nell'ambiente di esecuzione
load_dotenv()

from src.llm_resilience import ResilientGroqClient, PRIMARY_FREE_MODEL, FALLBACK_FREE_MODEL


def make_rate_limit_error(msg="Rate limit free tier raggiunto (TPM/RPM exceeded)"):
    """Genera un'eccezione HTTP 429 autentica di OpenAI/Groq."""
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError(message=msg, response=response, body=None)


# ==============================================================================
# SCENARIO 1: ERRORE INTERMITTENTE (Il retry risolve senza bisogno di fallback)
# ==============================================================================

def test_intermittent_429_self_heals_on_retry():
    print("\n" + "=" * 70)
    print("[STRESS TEST 1] Errore 429 intermittente sul modello 70B (Auto-ripristino)")
    print("=" * 70)

    mock_client = MagicMock()
    success_resp = MagicMock()
    success_resp.choices = [MagicMock(message=MagicMock(content="Accordo di bergamotto e cedro d'autore."))]

    # Tentativo 1: 429 -> Tentativo 2 (Retry): Successo
    mock_client.chat.completions.create.side_effect = [
        make_rate_limit_error(),
        success_resp
    ]

    resilient = ResilientGroqClient(mock_client, max_retries=2, base_delay=0.1)
    
    start_time = time.time()
    result = resilient.create_completion(messages=[{"role": "user", "content": "Cerco note agrumate"}])
    elapsed = time.time() - start_time

    print(f"  -> Tentativi totali eseguiti: {mock_client.chat.completions.create.call_count}")
    print(f"  -> Modello usato per la risposta: {mock_client.chat.completions.create.call_args[1]['model']}")
    print(f"  -> Tempo di backoff calcolato: {elapsed:.3f}s")
    print(f"  -> Risultato ottenuto: \"{result}\"")

    assert result == "Accordo di bergamotto e cedro d'autore."
    assert mock_client.chat.completions.create.call_count == 2
    assert mock_client.chat.completions.create.call_args[1]["model"] == PRIMARY_FREE_MODEL
    print("[PASSATO] Il sistema ha gestito il rate limit senza disturbare il modello di fallback.")


# ==============================================================================
# SCENARIO 2: QUOTA 70B ESAURITA (Transizione fluida sul modello Fallback 8B)
# ==============================================================================

def test_complete_primary_saturation_transitions_to_fallback():
    print("\n" + "=" * 70)
    print("[STRESS TEST 2] Quota 70B satura -> Transizione automatica su 8B rapido")
    print("=" * 70)

    mock_client = MagicMock()
    fallback_resp = MagicMock()
    fallback_resp.choices = [MagicMock(message=MagicMock(content="Risposta generata dal modello 8B Instant."))]

    # 3 fallimenti sul 70B (1 primario + 2 retry) -> Successo su 8B
    mock_client.chat.completions.create.side_effect = [
        make_rate_limit_error("70B saturato #1"),
        make_rate_limit_error("70B saturato #2"),
        make_rate_limit_error("70B saturato #3"),
        fallback_resp
    ]

    resilient = ResilientGroqClient(mock_client, max_retries=2, base_delay=0.05)

    start_time = time.time()
    result = resilient.create_completion(messages=[{"role": "user", "content": "Consiglio profumo sera"}])
    elapsed = time.time() - start_time

    all_calls = mock_client.chat.completions.create.call_args_list
    print(f"  -> Chiamate totali: {len(all_calls)}")
    for idx, call in enumerate(all_calls, 1):
        print(f"     Chiamata #{idx}: Modello richiesto = {call[1]['model']}")

    print(f"  -> Tempo totale con backoff: {elapsed:.3f}s")
    print(f"  -> Risposta finale: \"{result}\"")

    assert result == "Risposta generata dal modello 8B Instant."
    assert len(all_calls) == 4
    assert all_calls[0][1]["model"] == PRIMARY_FREE_MODEL
    assert all_calls[1][1]["model"] == PRIMARY_FREE_MODEL
    assert all_calls[2][1]["model"] == PRIMARY_FREE_MODEL
    assert all_calls[3][1]["model"] == FALLBACK_FREE_MODEL
    print("[PASSATO] Fallback eseguito con successo esattamente al momento corretto.")


# ==============================================================================
# SCENARIO 3: CONCORRENZA MULTI-THREAD (10 Utenti simultanei sul server)
# ==============================================================================

def test_multithreaded_burst_traffic():
    print("\n" + "=" * 70)
    print("[STRESS TEST 3] Concorrenza: 10 utenti simultanei (alcuni in 429, altri OK)")
    print("=" * 70)

    call_counter = 0

    def mock_create(*args, **kwargs):
        nonlocal call_counter
        call_counter += 1
        model = kwargs.get("model")
        # Simula instabilità: 1 richiesta su 2 del 70B restituisce 429; l'8B risponde sempre subito
        if model == PRIMARY_FREE_MODEL and (call_counter % 2 == 1):
            raise make_rate_limit_error(f"Picco traffico simulato su {model}")
        
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=f"Risposta OK per sessione ({model})"))]
        return resp

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_create

    resilient = ResilientGroqClient(mock_client, max_retries=1, base_delay=0.02)

    num_threads = 10
    responses = []

    start = time.time()
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [
            executor.submit(resilient.create_completion, [{"role": "user", "content": f"User {i}"}])
            for i in range(num_threads)
        ]
        for f in as_completed(futures):
            responses.append(f.result())
    total_time = time.time() - start

    print(f"  -> Utenti serviti in parallelo: {len(responses)}/{num_threads}")
    print(f"  -> Chiamate totali processate dal wrapper: {call_counter}")
    print(f"  -> Tempo totale burst: {total_time:.3f}s")
    for idx, r in enumerate(responses[:4], 1):
        print(f"     Campione risposta #{idx}: {r}")

    # Nessun thread deve essere andato in crash o aver sollevato eccezioni
    assert len(responses) == num_threads
    assert all("Risposta OK" in r for r in responses)
    print("[PASSATO] 100% delle richieste concorrenti portate a termine senza errori 500.")


# ==============================================================================
# SCENARIO 4: BLACKOUT TOTALE (Nessun crash, messaggio di cortesia sicuro)
# ==============================================================================

def test_total_api_outage_graceful_response():
    print("\n" + "=" * 70)
    print("[STRESS TEST 4] Blackout totale delle API (Sia 70B che 8B irraggiungibili)")
    print("=" * 70)

    mock_client = MagicMock()
    # Entrambi i modelli falliscono sistematicamente per timeout/down
    mock_client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())

    resilient = ResilientGroqClient(mock_client, max_retries=1, base_delay=0.01)

    result = resilient.create_completion(
        messages=[{"role": "user", "content": "C'è qualcuno?"}],
        graceful_fallback_text="Il nostro Maître Parfumeur è momentaneamente assente per assortimento."
    )

    print(f"  -> Risultato di emergenza restituito al frontend: \"{result}\"")
    assert result == "Il nostro Maître Parfumeur è momentaneamente assente per assortimento."
    print("[PASSATO] Nessun errore 500: l'applicazione gestisce il disservizio con eleganza.")


# ==============================================================================
# SCENARIO 5: TEST LIVE SU GROQ A 0€ (Chiamate reali end-to-end)
# ==============================================================================

@pytest.mark.e2e
def test_live_dual_model_execution_on_groq():
    """TEST REALE LIVE: Interroga realmente Groq a costo 0€ sia sul 70B che sull'8B.
    Simula poi un rate limit forzato sul 70B per validare la risposta reale dell'8B."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY non presente nel file .env, skip del test live.")

    print("\n" + "=" * 70)
    print("[STRESS TEST 5 - LIVE GROQ] Esecuzione reale dei due modelli gratuiti")
    print("=" * 70)

    real_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    resilient = ResilientGroqClient(real_client, max_retries=1, base_delay=0.5)

    # 1. Chiamata reale al modello Primario 70B
    print(f"  [1/3] Invio richiesta reale al modello PRIMARIO ({PRIMARY_FREE_MODEL})...")
    start = time.time()
    reply_70b = resilient.create_completion(
        messages=[{"role": "user", "content": "Descrivi l'accordo di vetiver in una frase raffinata."}],
        primary_model=PRIMARY_FREE_MODEL,
        max_tokens=60
    )
    t_70b = time.time() - start
    print(f"        -> Risposta 70B ({t_70b:.2f}s): \"{reply_70b}\"")
    assert len(reply_70b) > 10

    # 2. Chiamata reale al modello Fallback 8B
    print(f"  [2/3] Invio richiesta reale al modello FALLBACK ({FALLBACK_FREE_MODEL})...")
    start = time.time()
    reply_8b = resilient.create_completion(
        messages=[{"role": "user", "content": "Descrivi l'accordo di vetiver in una frase raffinata."}],
        primary_model=FALLBACK_FREE_MODEL,
        fallback_model=FALLBACK_FREE_MODEL,
        max_tokens=60
    )
    t_8b = time.time() - start
    print(f"        -> Risposta 8B ({t_8b:.2f}s): \"{reply_8b}\"")
    assert len(reply_8b) > 10

    # 3. Test Fallback Forzato dal Vivo:
    # Usiamo un wrapper che simula 429 sul 70B, ma lascia passare all'API REALE di Groq l'8B
    print("  [3/3] Simulazione LIVE: Primario restituisce 429 forzato -> Fallback chiama davvero Groq 8B...")
    hybrid_client = MagicMock()

    def fake_create(**kwargs):
        if kwargs.get("model") == PRIMARY_FREE_MODEL:
            raise make_rate_limit_error("Simulazione saturazione TPM 70B")
        # Se è l'8B, effettua la vera chiamata API a Groq
        return real_client.chat.completions.create(**kwargs)

    hybrid_client.chat.completions.create.side_effect = fake_create

    live_resilient = ResilientGroqClient(hybrid_client, max_retries=1, base_delay=0.1)
    start = time.time()
    live_fallback_reply = live_resilient.create_completion(
        messages=[{"role": "user", "content": "Come si comporta il sandalo sulla pelle d'inverno? Rispondi in una frase."}],
        primary_model=PRIMARY_FREE_MODEL,
        fallback_model=FALLBACK_FREE_MODEL,
        max_tokens=60
    )
    t_live = time.time() - start
    print(f"        -> Risposta REALE generata dal fallback 8B ({t_live:.2f}s): \"{live_fallback_reply}\"")
    
    assert len(live_fallback_reply) > 10
    print("[PASSATO] Il fallback live su Groq 8B funziona perfettamente a costo zero.")