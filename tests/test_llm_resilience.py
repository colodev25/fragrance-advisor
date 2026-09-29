import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock
import httpx
import pytest
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, APITimeoutError, InternalServerError

# Caricamento esplicito delle variabili d'ambiente per abilitare i test live
load_dotenv()

from src.llm_resilience import ResilientGroqClient, PRIMARY_FREE_MODEL, FALLBACK_FREE_MODEL


def make_rate_limit_error(msg="Rate limit superato (TPM/RPM exceeded)"):
    """Costruisce un'eccezione HTTP 429 identica a quella generata dall'SDK di OpenAI/Groq."""
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError(message=msg, response=response, body=None)


# ==============================================================================
# SCENARIO 1: BACKOFF TEMPORALE E AUTO-RIPRISTINO SUL MODELLO 120B
# ==============================================================================

def test_exponential_backoff_timing_and_recovery():
    """Verifica che il backoff rispetti l'intervallo temporale atteso (base_delay * 2^attempt)
    e che il modello 120B completi la richiesta appena il rate limit si sblocca."""
    print("\n" + "=" * 75)
    print(f"[STRESS TEST 1] Backoff Esponenziale e Ripristino su {PRIMARY_FREE_MODEL}")
    print("=" * 75)

    mock_client = MagicMock()
    success_resp = MagicMock()
    success_resp.choices = [MagicMock(message=MagicMock(content="Accordo di rosa damascena e zafferano."))]

    # Tentativo 0: fallisce per 429 -> attesa 0.15s
    # Tentativo 1: successo
    mock_client.chat.completions.create.side_effect = [
        make_rate_limit_error(),
        success_resp
    ]

    base_delay = 0.15
    resilient = ResilientGroqClient(mock_client, max_retries=2, base_delay=base_delay)

    start = time.perf_counter()
    reply = resilient.create_completion(messages=[{"role": "user", "content": "Note speziate"}])
    elapsed = time.perf_counter() - start

    call_args_list = mock_client.chat.completions.create.call_args_list
    print(f"  -> Chiamate effettuate: {len(call_args_list)}")
    print(f"  -> Modello chiamata #1: {call_args_list[0][1]['model']}")
    print(f"  -> Modello chiamata #2: {call_args_list[1][1]['model']}")
    print(f"  -> Tempo trascorso: {elapsed:.3f}s (atteso >= {base_delay:.2f}s)")
    print(f"  -> Output: \"{reply}\"")

    # Asserzioni stringenti
    assert reply == "Accordo di rosa damascena e zafferano."
    assert len(call_args_list) == 2
    assert call_args_list[0][1]["model"] == PRIMARY_FREE_MODEL
    assert call_args_list[1][1]["model"] == PRIMARY_FREE_MODEL
    assert elapsed >= base_delay, f"Il backoff non ha rispettato i tempi di attesa: {elapsed}s < {base_delay}s"
    print("  [ESITO] Backoff e auto-ripristino superati con timing accurato.")


# ==============================================================================
# SCENARIO 2: SATURAZIONE COMPLETA DEL 120B -> TRANSIZIONE SU 20B
# ==============================================================================

def test_full_primary_exhaustion_routes_to_secondary():
    """Verifica che dopo l'esaurimento di tutti i tentativi sul 120B,
    il traffico venga dirottato senza interruzioni sul modello 20B."""
    print("\n" + "=" * 75)
    print(f"[STRESS TEST 2] Saturazione {PRIMARY_FREE_MODEL} -> Passaggio a {FALLBACK_FREE_MODEL}")
    print("=" * 75)

    mock_client = MagicMock()
    fallback_resp = MagicMock()
    fallback_resp.choices = [MagicMock(message=MagicMock(content="Risposta erogata dal motore rapido 20B."))]

    # 1 chiamata iniziale + 2 retry sul 120B (tutti 429) -> 1 chiamata su 20B (successo)
    mock_client.chat.completions.create.side_effect = [
        make_rate_limit_error("120B saturato #1"),
        make_rate_limit_error("120B saturato #2"),
        make_rate_limit_error("120B saturato #3"),
        fallback_resp
    ]

    resilient = ResilientGroqClient(mock_client, max_retries=2, base_delay=0.03)
    reply = resilient.create_completion(messages=[{"role": "user", "content": "Consiglio serale"}])

    calls = mock_client.chat.completions.create.call_args_list
    print(f"  -> Sequenza chiamate ({len(calls)} tentativi totali):")
    for i, c in enumerate(calls, 1):
        print(f"     Tentativo {i}: model='{c[1]['model']}'")

    print(f"  -> Risposta finale ricevuta: \"{reply}\"")

    assert reply == "Risposta erogata dal motore rapido 20B."
    assert len(calls) == 4
    # Le prime 3 chiamate devono essere sul modello pesante primario
    for i in range(3):
        assert calls[i][1]["model"] == PRIMARY_FREE_MODEL
    # La quarta deve essere sul modello leggero di fallback
    assert calls[3][1]["model"] == FALLBACK_FREE_MODEL
    print("  [ESITO] Failover sul modello 20B eseguito nell'ordine corretto.")


# ==============================================================================
# SCENARIO 3: TRAFFICO BURST MULTI-THREAD CON ERRORI CASUALI
# ==============================================================================

def test_multithreaded_burst_traffic_resilience():
    """Simula 12 richieste simultanee. Alcune incappano nel 429 sul 120B
    mentre il 20B risponde; verifica l'assenza di race condition e zero errori 500."""
    print("\n" + "=" * 75)
    print("[STRESS TEST 3] Concorrenza: 12 richieste simultanee con instabilità simulata")
    print("=" * 75)

    call_count = 0

    def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        model = kwargs.get("model")
        # Il 120B fallisce su chiamate dispari per simulare rate-limit intermittente sotto carico
        if model == PRIMARY_FREE_MODEL and (call_count % 2 == 1):
            raise make_rate_limit_error("Quota istantanea 120B satura")
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=f"OK da {model}"))]
        return resp

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = mock_create

    resilient = ResilientGroqClient(mock_client, max_retries=1, base_delay=0.02)
    workers = 12
    results = []

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(resilient.create_completion, [{"role": "user", "content": f"Query {i}"}])
            for i in range(workers)
        ]
        for f in as_completed(futures):
            results.append(f.result())
    elapsed = time.perf_counter() - start

    print(f"  -> Richieste completate con successo: {len(results)}/{workers}")
    print(f"  -> Chiamate API complessive gestite dal wrapper: {call_count}")
    print(f"  -> Tempo totale burst: {elapsed:.3f}s")

    assert len(results) == workers
    # Nessun thread deve aver fallito o sollevato eccezioni
    assert all("OK da openai/gpt-oss-" in r for r in results)
    print("  [ESITO] Tutte le richieste concorrenti sono state assorbite senza crash.")


# ==============================================================================
# SCENARIO 4: BLACKOUT TOTALE DELLE API (Graceful Degradation)
# ==============================================================================

def test_total_api_failure_graceful_degradation():
    """Verifica che in caso di guasto totale (timeout o crash sia su 120B che su 20B),
    il client non sollevi mai eccezioni al chiamante ma fornisca un messaggio amichevole."""
    print("\n" + "=" * 75)
    print("[STRESS TEST 4] Blackout totale (Tutti i modelli irraggiungibili)")
    print("=" * 75)

    mock_client = MagicMock()
    # Entrambi i modelli falliscono sistematicamente con errori 500 del provider
    mock_client.chat.completions.create.side_effect = InternalServerError(
        message="Groq upstream server error", response=MagicMock(status_code=500), body=None
    )

    resilient = ResilientGroqClient(mock_client, max_retries=1, base_delay=0.01)
    custom_msg = "Attualmente i nostri profumieri sono tutti impegnati."

    reply = resilient.create_completion(
        messages=[{"role": "user", "content": "Cerco agrumato"}],
        graceful_fallback_text=custom_msg
    )

    print(f"  -> Risposta di sicurezza: \"{reply}\"")
    assert reply == custom_msg
    print("  [ESITO] Graceful degradation verificata con successo.")


# ==============================================================================
# SCENARIO 5: TEST DI INTEGRAZIONE LIVE SULLE API REALI A COSTO 0€
# ==============================================================================

@pytest.mark.e2e
def test_live_execution_on_active_models():
    """Interroga realmente l'endpoint Groq sui due modelli effettivi (120B e 20B).
    Simula poi un failover live per confermare che il 20B generi testo valido."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY non rilevata in .env, skip del test live.")

    print("\n" + "=" * 75)
    print(f"[STRESS TEST 5 - LIVE GROQ] Esecuzione reale: {PRIMARY_FREE_MODEL} e {FALLBACK_FREE_MODEL}")
    print("=" * 75)

    real_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    resilient = ResilientGroqClient(real_client, max_retries=1, base_delay=0.5)

    # 1. Chiamata reale al modello Primario 120B
    print(f"  [1/3] Interrogazione reale modello PRIMARIO ({PRIMARY_FREE_MODEL})...")
    start = time.perf_counter()
    reply_120b = resilient.create_completion(
        messages=[{"role": "user", "content": "Definisci in una sola frase elegante il concetto di sillage."}],
        primary_model=PRIMARY_FREE_MODEL,
        max_tokens=250
    )
    t_120b = time.perf_counter() - start
    print(f"        -> Risposta 120B ({t_120b:.2f}s): \"{reply_120b}\"")
    assert len(reply_120b) > 15
    assert "Maître Parfumeur" not in reply_120b

    # 2. Chiamata reale al modello Fallback 20B
    print(f"  [2/3] Interrogazione reale modello FALLBACK ({FALLBACK_FREE_MODEL})...")
    start = time.perf_counter()
    reply_20b = resilient.create_completion(
        messages=[{"role": "user", "content": "Definisci in una sola frase elegante il concetto di sillage."}],
        primary_model=FALLBACK_FREE_MODEL,
        fallback_model=FALLBACK_FREE_MODEL,
        max_tokens=250
    )
    t_20b = time.perf_counter() - start
    print(f"        -> Risposta 20B ({t_20b:.2f}s): \"{reply_20b}\"")
    assert len(reply_20b) > 15
    assert "Maître Parfumeur" not in reply_20b

    # 3. Failover Live simulato: il 120B genera un 429 simulato e il 20B risponde realmente da Groq
    print(f"  [3/3] Failover Live: 120B in errore forzato -> Chiamata reale a {FALLBACK_FREE_MODEL}...")
    hybrid_client = MagicMock()

    def fake_create(**kwargs):
        if kwargs.get("model") == PRIMARY_FREE_MODEL:
            raise make_rate_limit_error("Simulazione saturazione quota 120B")
        # Inoltra la chiamata all'API reale di Groq sul modello 20B
        return real_client.chat.completions.create(**kwargs)

    hybrid_client.chat.completions.create.side_effect = fake_create

    live_resilient = ResilientGroqClient(hybrid_client, max_retries=1, base_delay=0.1)
    start = time.perf_counter()
    live_fallback_reply = live_resilient.create_completion(
        messages=[{"role": "user", "content": "Descrivi la nota olfattiva del bergamotto in poche parole."}],
        primary_model=PRIMARY_FREE_MODEL,
        fallback_model=FALLBACK_FREE_MODEL,
        max_tokens=250
    )
    t_live = time.perf_counter() - start
    print(f"        -> Risposta live da 20B ({t_live:.2f}s): \"{live_fallback_reply}\"")

    assert len(live_fallback_reply) > 15
    assert "Maître Parfumeur" not in live_fallback_reply
    print("  [ESITO] Test end-to-end con i modelli operativi superato al 100%.")