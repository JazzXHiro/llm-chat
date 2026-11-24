"""422 for bad input, 404 for unknown sessions. Nothing is stored for a rejected request."""

import pytest

from tests.helpers import chat


@pytest.mark.parametrize(
    "body",
    [
        {"message": "hi"},  # session_id missing
        {"session_id": "s1"},  # message missing
        {"session_id": "", "message": "hi"},  # session_id too short
        {"session_id": "x" * 129, "message": "hi"},  # session_id too long
        {"session_id": "s1", "message": ""},  # empty message
        {"session_id": "s1", "message": "    \n\t  "},  # only whitespace -> empty after trim
        {"session_id": "s1", "message": "x" * 4001},  # message too long
        {"session_id": "s1", "message": 123},  # wrong type
        {"session_id": "s1", "message": "hi", "system_prompt": "x" * 4001},  # prompt too long
    ],
)
def test_invalid_chat_body_is_422(client, body):
    response = client.post("/chat", json=body)
    assert response.status_code == 422
    assert "detail" in response.json()
    # A rejected request must not create the session
    assert client.get("/sessions/s1/messages").status_code == 404


def test_malformed_json_is_422(client):
    response = client.post(
        "/chat", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "detail" in response.json()


def test_limits_are_inclusive(client):
    """Exactly 128 / 4000 characters is allowed."""
    response = chat(client, session_id="s" * 128, message="m" * 4000)
    assert response.status_code == 200


def test_message_is_trimmed_before_saving(client):
    chat(client, message="   hello   ")
    messages = client.get("/sessions/s1/messages").json()["messages"]
    assert messages[0]["content"] == "hello"


def test_unknown_session_history_is_404(client):
    response = client.get("/sessions/does-not-exist/messages")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_unknown_route_is_json_not_html(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
