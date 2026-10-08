"""Offline by default; real provider calls require --live-services explicitly."""
import ipaddress
import os
import socket

import pytest


def pytest_addoption(parser):
    parser.addoption("--live-services", action="store_true", default=False,
                     help="Allow external services and real credentials (may consume quota).")


def pytest_sessionstart(session):
    if session.config.getoption("--live-services"):
        return
    patch = pytest.MonkeyPatch()
    patch.setenv("GROQ_API_KEY", "offline-test-key-not-a-secret")
    patch.setenv("SESSIONS_DB_PATH", str(session.config._tmp_path_factory.getbasetemp() / "sessions.db"))
    patch.setenv("ANONYMIZED_TELEMETRY", "False")
    session.config.add_cleanup(patch.undo)


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live-services"):
        skip = pytest.mark.skip(reason="Real services require --live-services explicitly")
        for item in items:
            if item.get_closest_marker("e2e"):
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def offline_network(request, monkeypatch):
    if request.config.getoption("--live-services"):
        return

    def check_host(host):
        if isinstance(host, bytes):
            host = host.decode("ascii")
        if host == "localhost":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise RuntimeError("External network access is disabled during offline tests")

    original_resolve = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def resolve(host, *args, **kwargs):
        check_host(host)
        return original_resolve(host, *args, **kwargs)

    def connect(sock, address):
        if isinstance(address, tuple):
            check_host(address[0])
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if isinstance(address, tuple):
            check_host(address[0])
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
