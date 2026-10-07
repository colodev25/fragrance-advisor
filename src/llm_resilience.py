import os
import time
import logging
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Optional, Callable
from openai import OpenAI, RateLimitError, APIConnectionError, APITimeoutError, InternalServerError

logger = logging.getLogger("fragrance_advisor.llm")

# Modelli attivi e verificati sull'endpoint Groq
PRIMARY_FREE_MODEL = os.getenv("GROQ_PRIMARY_MODEL", "openai/gpt-oss-120b")
FALLBACK_FREE_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")


def retry_after_seconds(error):
    """Read only the safe retry header, never log the provider response body."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {})
    value = headers.get("retry-after") if headers is not None else None
    if not isinstance(value, str):
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


class InvalidCompletion(ValueError):
    def __init__(self, kind):
        self.kind = kind
        super().__init__(kind)


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
        reasoning_effort: Optional[str] = None,
        recover_truncated: bool = True,
        max_retry_delay: float = 30.0,
        failure_callback: Optional[Callable[[str, Optional[float]], None]] = None,
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
                    if reasoning_effort is not None:
                        kwargs["reasoning_effort"] = reasoning_effort

                    response = self.client.chat.completions.create(**kwargs)
                    choice = response.choices[0]
                    content = (choice.message.content or "").strip()

                    # Recupero automatico se il reasoning ha saturato il budget di token
                    if not content:
                        finish_reason = getattr(choice, "finish_reason", None)
                        if recover_truncated and finish_reason == "length" and max_tokens is not None:
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

                        raise InvalidCompletion("truncated_response" if finish_reason == "length" else "empty_response")

                    if getattr(choice, "finish_reason", None) == "length":
                        raise InvalidCompletion("truncated_response")
                    if response_validator:
                        response_validator(content)
                    return content

                except (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError) as e:
                    kind = ("rate_limit" if isinstance(e, RateLimitError) else
                            "timeout" if isinstance(e, APITimeoutError) else
                            "connection_error" if isinstance(e, APIConnectionError) else "server_error")
                    hint = retry_after_seconds(e)
                    delay = max(self.base_delay * (2 ** attempt), hint or 0.0)
                    if attempt < self.max_retries and delay <= max_retry_delay:
                        logger.warning("[GROQ %s] %s, tentativo %s: attendo %.1fs prima del retry.", kind.upper(), model, attempt + 1, delay)
                        time.sleep(delay)
                    else:
                        logger.warning("[GROQ %s] %s, tentativo %s: nessun ulteriore retry su questo modello; Retry-After=%s.", kind.upper(), model, attempt + 1, hint)
                        if failure_callback:
                            failure_callback(kind, hint)
                        break

                except Exception as e:
                    status = getattr(e, "status_code", None)
                    kind = (e.kind if isinstance(e, InvalidCompletion) else
                            "authentication_error" if status in (401, 403) else
                            "request_error" if isinstance(status, int) and 400 <= status < 500 else
                            "invalid_response" if isinstance(e, ValueError) else "unexpected_error")
                    logger.error("[GROQ %s] %s (%s).", kind.upper(), model, type(e).__name__)
                    if failure_callback:
                        failure_callback(kind, None)
                    break

        logger.error("Nessuna risposta valida disponibile dai modelli configurati.")
        return graceful_fallback_text
