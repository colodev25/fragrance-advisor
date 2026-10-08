"""The default suite must never consume provider quota or use production state."""
import os
import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def only_offline(request):
    if request.config.getoption("--live-services"):
        pytest.skip("Checks for the default offline policy")


def test_default_credentials_and_database_are_isolated(tmp_path_factory):
    assert os.environ["GROQ_API_KEY"] == "offline-test-key-not-a-secret"
    assert Path(os.environ["SESSIONS_DB_PATH"]).parent == tmp_path_factory.getbasetemp()


def test_external_dns_resolution_is_blocked():
    with pytest.raises(RuntimeError, match="External network access"):
        socket.getaddrinfo("api.groq.com", 443)


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_external_ip_connections_are_blocked(method):
    with socket.socket() as connection:
        with pytest.raises(RuntimeError, match="External network access"):
            getattr(connection, method)(("192.0.2.1", 443))


def test_loopback_resolution_remains_available_for_http_tests():
    assert socket.getaddrinfo("127.0.0.1", 80)
