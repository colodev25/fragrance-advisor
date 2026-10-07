from src.rate_limit import InMemoryRateLimiter


def test_allows_requests_until_the_route_limit_is_reached():
    limiter = InMemoryRateLimiter()

    assert limiter.allow("chat:127.0.0.1", limit=2) == (True, 0)
    assert limiter.allow("chat:127.0.0.1", limit=2) == (True, 0)

    allowed, retry_after = limiter.allow("chat:127.0.0.1", limit=2)
    assert allowed is False
    assert retry_after >= 1


def test_routes_and_clients_have_independent_limits():
    limiter = InMemoryRateLimiter()

    assert limiter.allow("chat:client-a", limit=1) == (True, 0)
    assert limiter.allow("reset:client-a", limit=1) == (True, 0)
    assert limiter.allow("chat:client-b", limit=1) == (True, 0)
