"""Thread-safe, in-memory fixed-window protection for public API routes."""

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class InMemoryRateLimiter:
    """Tracks recent requests per client and route within a rolling time window."""

    def __init__(self, window_seconds: float = 60.0, max_keys: int = 10_000):
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._last_seen: dict[str, float] = {}
        self._lock = Lock()

    def allow(self, key: str, limit: int) -> tuple[bool, int]:
        """Return whether a request is allowed and, if blocked, its retry delay."""
        now = monotonic()

        with self._lock:
            timestamps = self._requests[key]
            cutoff = now - self.window_seconds
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            self._last_seen[key] = now
            self._prune(now)

            if len(timestamps) >= limit:
                retry_after = max(1, int(self.window_seconds - (now - timestamps[0])) + 1)
                return False, retry_after

            timestamps.append(now)
            return True, 0

    def reset(self) -> None:
        """Clear counters. Used by tests and local development only."""
        with self._lock:
            self._requests.clear()
            self._last_seen.clear()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        expired = [key for key, seen_at in self._last_seen.items() if seen_at <= cutoff]
        for key in expired:
            self._requests.pop(key, None)
            self._last_seen.pop(key, None)

        if len(self._requests) <= self.max_keys:
            return

        oldest_keys = sorted(self._last_seen, key=self._last_seen.get)
        for key in oldest_keys[: len(self._requests) - self.max_keys]:
            self._requests.pop(key, None)
            self._last_seen.pop(key, None)
