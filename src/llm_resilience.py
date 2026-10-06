import os
import time
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI, RateLimitError, APIConnectionError, APITimeoutError, InternalServerError

logger = logging.getLogger("fragrance_advisor.llm")

# Modelli attivi e verificati sull'endpoint Groq
PRIMARY_FREE_MODEL = os.getenv("GROQ_PRIMARY_MODEL", "openai/gpt-oss-120b")
FALLBACK_FREE_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")


class ResilientGroqClient:
    """Gestore resiliente per le API gratuite di Groq con Exponential Backoff, Fallback e Reasoning Recovery."""

    def __init__(self, client: OpenAI, max_retries: int = 2, base_delay: float = 0.8):
        self.client = client
        self.max_retries = max_retries
        self.base_delay = base_delay

    def create_completion(
        self,
        messages: List[Dict[str, str]],
        primary_model: str = PRIMARY_FREE_MODEL,
        fallback_model: str = FALLBACK_FREE_MODEL,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        graceful_fallback_text: str = (
            "Il nostro Maître Parfumeur sta ricevendo molte richieste in questo istante. "
            "Ti invitiamo a riformulare o a riprovare tra qualche secondo."
        )
    ) -> str:
        """
        Invia la richiesta al modello primario gratuito. Se incontra rate limit (429)
        o risposte troncate dal reasoning, prova il retry e scala sul fallback.
        """
        models_to_try = [primary_model]
        if fallback_model and fallback_model != primary_model:
            models_to_try.append(fallback_model)

        last_exception = None

        for model in models_to_try:
            is_fallback = (model != primary_model)
            if is_fallback:
                logger.warning(f"[GROQ FREE FALLBACK] Attivazione modello di riserva gratuito: {model}")

            for attempt in range(self.max_retries + 1):
                try:
                    kwargs: Dict[str, Any] = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                    }
                    if max_tokens is not None:
                        kwargs["max_tokens"] = max_tokens

                    response = self.client.chat.completions.create(**kwargs)
                    choice = response.choices[0]
                    content = (choice.message.content or "").strip()

                    # Recupero automatico se il reasoning ha saturato il budget di token
                    if not content:
                        finish_reason = getattr(choice, "finish_reason", None)
                        if finish_reason == "length" and max_tokens is not None:
                            extended_tokens = max(max_tokens * 2, 600)
                            logger.warning(
                                f"[GROQ REASONING TRUNCATED] {model} ha esaurito i {max_tokens} token "
                                f"nella catena di pensiero. Riprovo con budget esteso a {extended_tokens}..."
                            )
                            kwargs["max_tokens"] = extended_tokens
                            retry_resp = self.client.chat.completions.create(**kwargs)
                            retry_choice = retry_resp.choices[0]
                            retry_content = (retry_choice.message.content or "").strip()
                            if retry_content:
                                return retry_content

                        # Fallback secondario: se disponibile, recupera il reasoning process
                        reasoning = (
                            getattr(choice.message, "reasoning_content", None) or 
                            getattr(choice.message, "reasoning", None)
                        )
                        if reasoning and len(reasoning.strip()) > 15:
                            logger.warning(f"[GROQ REASONING EXTRACTED] Estratto reasoning per {model} poiché content era vuoto.")
                            return reasoning.strip()

                        raise ValueError(f"Il modello {model} ha restituito un testo vuoto.")

                    return content

                except (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError) as e:
                    last_exception = e
                    delay = self.base_delay * (2 ** attempt)
                    logger.warning(
                        f"[GROQ FREE LIMIT] Quota o timeout su {model} (tentativo {attempt + 1}): {e}. "
                        f"Attesa di {delay:.1f}s..."
                    )
                    time.sleep(delay)

                except Exception as e:
                    logger.error(f"[GROQ UNEXPECTED] Errore o risposta non valida su {model}: {e}")
                    last_exception = e
                    break

        logger.error(f"[GROQ LIMIT EXCEEDED] Limiti del piano free superati su tutti i modelli gratuiti: {last_exception}")
        return graceful_fallback_text