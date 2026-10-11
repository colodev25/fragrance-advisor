"""Process-local admission and provider budgets; never queue customer requests."""

import asyncio
import logging
import math
import os
import time
from collections import deque
from contextvars import ContextVar
from threading import Lock

try:
    from src.chat_budget import ChatUnavailable
except ModuleNotFoundError:
    from chat_budget import ChatUnavailable

logger = logging.getLogger("fragrance_advisor.capacity")


def positive_setting(name, default):
    try:
        value = int(os.getenv(name, default))
        if value > 0:
            return value
    except ValueError:
        pass
    logger.warning("Invalid %s; using %s.", name, default)
    return default


class AdmissionGate:
    def __init__(self, limit):
        self.limit = limit
        self.active = 0
        self._lock = Lock()

    def acquire(self):
        with self._lock:
            if self.active >= self.limit:
                return False
            self.active += 1
            return True

    def release(self):
        with self._lock:
            self.active -= 1


class ProviderCapacity:
    """One rolling call allowance and cooldown for all chat models in this process."""

    def __init__(self, limit=20, cooldown_seconds=5, clock=time.monotonic):
        self.limit = limit
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self._calls = deque()
        self._retry_until = 0.0
        self._lock = Lock()

    def reserve(self):
        with self._lock:
            now = self.clock()
            while self._calls and self._calls[0] <= now - 60:
                self._calls.popleft()
            delay = self._retry_until - now
            if delay > 0:
                raise ChatUnavailable("llm_rate_limit", max(1, math.ceil(delay)))
            if len(self._calls) >= self.limit:
                delay = max(1, math.ceil(60 - (now - self._calls[0])))
                logger.warning("Provider call allowance exhausted; retry_after=%s", delay)
                raise ChatUnavailable("llm_rate_limit", delay)
            self._calls.append(now)

    def defer(self, seconds=None):
        delay = seconds if seconds is not None and seconds > 0 else self.cooldown_seconds
        with self._lock:
            self._retry_until = max(self._retry_until, self.clock() + delay)
        logger.warning("Provider cooldown activated; retry_after=%s", math.ceil(delay))
        return delay


current_provider_capacity = ContextVar("current_provider_capacity", default=None)
provider_capacity = ProviderCapacity(
    positive_setting("GROQ_CHAT_CALLS_PER_MINUTE", 20),
    positive_setting("GROQ_CHAT_COOLDOWN_SECONDS", 5),
)
api_gate = AdmissionGate(positive_setting("API_MAX_CONCURRENT_REQUESTS", 2))


async def run_admitted(request, callback, *args):
    """Keep admission occupied if the HTTP task ends before its worker finishes."""
    def work():
        token = current_provider_capacity.set(provider_capacity)
        try:
            return callback(*args)
        finally:
            current_provider_capacity.reset(token)

    task = asyncio.create_task(asyncio.to_thread(work))
    request.scope["state"]["capacity_worker"] = task
    # Retrieve an abandoned worker's exception without logging customer data.
    task.add_done_callback(lambda completed: completed.exception() if not completed.cancelled() else None)
    return await asyncio.shield(task)


class CapacityMiddleware:
    def __init__(self, app, gate=api_gate, max_bytes=None, body_timeout=None):
        self.app = app
        self.gate = gate
        self.max_bytes = max_bytes or positive_setting("API_MAX_BODY_BYTES", 16 * 1024)
        self.body_timeout = body_timeout or positive_setting("API_BODY_TIMEOUT_SECONDS", 5)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"].rstrip("/") not in {"/chat", "/reset"}:
            return await self.app(scope, receive, send)

        async def reject(status, code, message, retry=None):
            # Catalog jobs import the provider guard without the API dependencies.
            from starlette.responses import JSONResponse
            logger.warning("API admission rejected; code=%s", code)
            response = JSONResponse(
                {"error": {"code": code, "message": message}}, status_code=status,
                headers={"Retry-After": str(retry)} if retry else None,
            )
            await response(scope, receive, send)

        headers = dict(scope.get("headers", []))
        if headers.get(b"content-encoding", b"identity").lower() != b"identity":
            return await reject(415, "unsupported_encoding", "Il formato della richiesta non è supportato.")
        if b"content-length" in headers:
            try:
                size = int(headers[b"content-length"])
                if size < 0:
                    raise ValueError
            except ValueError:
                return await reject(400, "invalid_content_length", "La richiesta non è valida.")
            if size > self.max_bytes:
                return await reject(413, "request_too_large", "La richiesta supera la dimensione consentita.")
        if not self.gate.acquire():
            return await reject(503, "service_capacity_exceeded", "Il servizio sta ricevendo molte richieste. Riprova tra qualche istante.", 2)

        state = scope.setdefault("state", {})
        started = time.monotonic()
        try:
            async def read_body():
                body = bytearray()
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return None
                    chunk = event.get("body", b"")
                    if len(body) + len(chunk) > self.max_bytes:
                        raise OverflowError
                    body.extend(chunk)
                    if not event.get("more_body", False):
                        return bytes(body)

            try:
                body = await asyncio.wait_for(read_body(), self.body_timeout)
            except OverflowError:
                return await reject(413, "request_too_large", "La richiesta supera la dimensione consentita.")
            except asyncio.TimeoutError:
                return await reject(408, "request_body_timeout", "L'invio della richiesta richiede troppo tempo. Riprova.")
            if body is None:
                return
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await self.app(scope, replay, send)
        finally:
            worker = state.get("capacity_worker")
            if worker is not None and not worker.done():
                worker.add_done_callback(lambda _: self.gate.release())
            else:
                self.gate.release()
            logger.info("API admission completed; duration_ms=%s", round((time.monotonic() - started) * 1000))
