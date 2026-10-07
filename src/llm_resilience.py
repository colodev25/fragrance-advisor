import os
import time
import logging
from typing import List, Dict, Any, Optional, Callable
from openai import OpenAI, RateLimitError, APIConnectionError, APITimeoutError, InternalServerError

logger = logging.getLogger("fragrance_advisor.llm")

# Modelli attivi e verificati sull'endpoint Groq
PRIMARY_FREE_MODEL = os.getenv("GROQ_PRIMARY_MODEL", "openai/gpt-oss-120b")
FALLBACK_FREE_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")


class ResilientGroqClient:
    """Retry e fallback Groq senza esporre il ragionamento interno."""

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
        ),
        response_validator: Optional[Callable[[str], Any]] = None,
    ) -> str:
        """
        Invia la richiesta al modello primario gratuito. Se incontra rate limit (429)
        o risposte troncate dal reasoning, prova il retry e scala sul fallback.
        """
        models_to_try = [primary_model]
        if fallback_model and fallback_model != primary_model:
            models_to_try.append(fallback_model)

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
                            if retry_content and getattr(retry_choice, "finish_reason", None) != "length":
                                if response_validator:
                                    response_validator(retry_content)
                                return retry_content

                        raise ValueError(f"Il modello {model} ha restituito un testo vuoto.")

                    if getattr(choice, "finish_reason", None) == "length":
                        raise ValueError("Risposta incompleta del modello.")
                    if response_validator:
                        response_validator(content)
                    return content

                except (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError) as e:
                    delay = self.base_delay * (2 ** attempt)
                    logger.warning(
                        f"[GROQ FREE LIMIT] Quota o timeout su {model} (tentativo {attempt + 1}). "
                        f"Attesa di {delay:.1f}s..."
                    )
                    if attempt < self.max_retries:
                        time.sleep(delay)

                except Exception as e:
                    logger.error("Risposta non valida o errore su %s (%s).", model, type(e).__name__)
                    break

        logger.error("Nessuna risposta valida disponibile dai modelli configurati.")
        return graceful_fallback_text
