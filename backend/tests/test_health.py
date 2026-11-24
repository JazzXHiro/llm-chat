"""GET /health"""

import socket

import pytest


def test_health_returns_exact_contract(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_health_counts_the_configured_keys(make_client):
    client = make_client(api_keys=["only-one-fake-key"])
    assert client.get("/health").json()["keys_configured"] == 1


def test_health_is_503_without_keys(make_client):
    client = make_client(api_keys=[])
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "no API keys configured"}


def test_tests_cannot_reach_the_internet():
    """Safety net from conftest.py: no test can ever call Gemini by accident."""
    with pytest.raises(RuntimeError, match="must not use the internet"):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)
