"""Key fallback: real (mocked) provider errors and the X-Simulate-Failure header."""

import pytest

from tests.helpers import RATE_LIMIT_ERROR, SERVER_ERROR, chat


# ---------- Provider errors (mock_response raises them), no header ----------

@pytest.mark.parametrize("error", [RATE_LIMIT_ERROR, SERVER_ERROR])
def test_key_1_error_falls_back_to_key_2(make_client, error):
    client = make_client(keys={"key_1": error})
    response = chat(client)
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "reply from key_2"
    assert body["metadata"]["key_id"] == "key_2"
    assert body["metadata"]["fallback_attempts"] == 1


def test_all_keys_failing_is_503_and_nothing_stored(make_client):
    client = make_client(keys={"key_1": RATE_LIMIT_ERROR, "key_2": SERVER_ERROR})
    response = chat(client, session_id="doomed")
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/doomed/messages").status_code == 404


# ---------- X-Simulate-Failure ----------

@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_simulated_key_1_failure_uses_key_2(client, status):
    response = chat(client, headers={"X-Simulate-Failure": f"key_1={status}"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "reply from key_2"
    assert body["metadata"]["key_id"] == "key_2"
    assert body["metadata"]["fallback_attempts"] == 1
    # the successful fallback turn IS stored
    assert len(client.get("/sessions/s1/messages").json()["messages"]) == 2


@pytest.mark.parametrize("header", ["*=429", "key_1=429,key_2=500"])
def test_every_key_failing_is_503_and_nothing_stored(client, header):
    response = chat(client, session_id="doomed", headers={"X-Simulate-Failure": header})
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/doomed/messages").status_code == 404


def test_failed_turn_is_not_added_to_an_existing_session(client):
    chat(client, message="ok turn")
    chat(client, message="bad turn", headers={"X-Simulate-Failure": "*=429"})
    messages = client.get("/sessions/s1/messages").json()["messages"]
    assert [m["content"] for m in messages if m["role"] == "user"] == ["ok turn"]


def test_simulation_only_affects_its_own_request(client):
    """Also checks disable_cooldowns: key_1 is not 'benched' after failing."""
    chat(client, session_id="a", headers={"X-Simulate-Failure": "*=429"})
    response = chat(client, session_id="b", message="normal request")
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_1"


@pytest.mark.parametrize("header", ["key_1", "key_1=abc", "key_1=404", "key_9=429", "key_1:429"])
def test_bad_simulation_header_is_422(client, header):
    response = chat(client, session_id="bad", headers={"X-Simulate-Failure": header})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("invalid X-Simulate-Failure header")
    assert client.get("/sessions/bad/messages").status_code == 404


def test_header_is_ignored_when_simulation_is_disabled(make_client):
    client = make_client(simulation=False)
    response = chat(client, headers={"X-Simulate-Failure": "*=429"})
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_1"
