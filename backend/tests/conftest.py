"""Shared test setup.

Rules for every test:
- Gemini is NEVER called. Each key in the Router gets a `mock_response`, so
  LiteLLM returns a fake reply (or raises a fake error) without any HTTP call.
- The internet is blocked: any DNS lookup of a non-local host fails the test.
- Every test gets its own empty SQLite file (pytest's tmp_path).
- The LiteLLM cache is global, so it is emptied before and after every test.
"""

import os

# LiteLLM downloads a model price list when it is imported. Use the copy
# bundled with the package instead (must be set BEFORE litellm is imported).
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import socket  # noqa: E402

import litellm  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from litellm import Router  # noqa: E402

import app.llm as llm_module  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.helpers import DEFAULT_PROMPT, FAKE_KEYS, MODEL, default_reply  # noqa: E402

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver", None}


@pytest.fixture(autouse=True)
def block_internet(monkeypatch):
    """Fail loudly if anything tries to reach a real server (e.g. Gemini)."""
    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in LOCAL_HOSTS:
            raise RuntimeError(f"Tests must not use the internet (tried to reach {host})")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def empty_llm_cache():
    """litellm.cache is one object for the whole process: start and end each test empty."""
    if litellm.cache is not None:
        litellm.cache.cache.flush_cache()
    yield
    if litellm.cache is not None:
        litellm.cache.cache.flush_cache()


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    """Factory: make_client(keys={"key_1": RATE_LIMIT_ERROR}, simulation=True) -> TestClient.

    `keys` says what each key does: a reply text, or an error string from
    tests/helpers.py. Keys not listed answer with "reply from key_N".
    """
    clients = []

    def _make(keys: dict[str, str] | None = None, simulation: bool = True, api_keys=FAKE_KEYS):
        behaviour = keys or {}

        def fake_keys_router(model_list, **kwargs):
            """The real LiteLLM Router (same fallbacks, hook and cache), but every
            key answers with mock_response instead of calling Gemini.
            (LiteLLM forbids subclassing Router, so we wrap it in a function.)"""
            for deployment in model_list:
                key_id = deployment["model_info"]["id"]
                deployment["litellm_params"]["mock_response"] = behaviour.get(
                    key_id, default_reply(key_id)
                )
            return Router(model_list=model_list, **kwargs)

        # app/llm.py builds its Router through this name -> it now gets ours
        monkeypatch.setattr(llm_module, "Router", fake_keys_router)

        settings = Settings(
            api_keys=list(api_keys),
            model=MODEL,
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            allowed_origins=["http://localhost:3000"],
            enable_failure_simulation=simulation,
            default_system_prompt=DEFAULT_PROMPT,
            llm_timeout_seconds=5,
        )
        client = TestClient(create_app(settings))
        client.__enter__()  # runs the lifespan: DB tables, Router, cache warm-up
        clients.append(client)
        return client

    yield _make

    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    """The normal case: 2 working keys, failure simulation switched on."""
    return make_client()

