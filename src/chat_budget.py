"""Budget cooperativo per una richiesta chat, isolato per thread/context."""

import math
import time
from contextvars import ContextVar


class ChatUnavailable(Exception):
    def __init__(self, code="llm_unavailable", retry_after=None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


class ChatBudget:
    TOTAL_SECONDS = 25.0
    MAX_CALLS = 3
    MAX_INLINE_WAIT = 1.0

    def __init__(self):
        self.deadline = time.monotonic() + self.TOTAL_SECONDS
        self.calls = 0
        self.retry_until = 0.0

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def retry_after(self):
        remaining = self.retry_until - time.monotonic()
        return math.ceil(remaining) if remaining > 0 else None

    def check_deadline(self):
        if self.remaining() <= 0:
            raise ChatUnavailable("chat_deadline_exceeded", self.retry_after())

    def check(self):
        self.check_deadline()
        if self.retry_after() is not None:
            raise ChatUnavailable("llm_rate_limit", self.retry_after())

    def reserve_call(self, call_timeout):
        self.check()
        if self.calls >= self.MAX_CALLS:
            raise ChatUnavailable("llm_attempts_exhausted")
        timeout = min(call_timeout, self.remaining())
        if timeout <= 0:
            raise ChatUnavailable("chat_deadline_exceeded")
        self.calls += 1
        return timeout

    def defer_retry(self, seconds):
        self.retry_until = max(self.retry_until, time.monotonic() + seconds)


current_chat_budget = ContextVar("current_chat_budget", default=None)
