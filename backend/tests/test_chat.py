"""POST /chat happy path and GET /sessions/{id}/messages."""

import pytest

from tests.helpers import DEFAULT_PROMPT, MODEL, chat

METADATA_FIELDS = {
    "resolution_source",
    "model",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "key_id",
    "fallback_attempts",
}


@pytest.fixture
def sent_to_llm(client):
    """Records the message list of every LLM call (the call itself still runs)."""
    sent = []
    llm = client.app.state.llm
    real_complete = llm.complete

    async def spy(messages, simulate=None):
        sent.append(messages)
        return await real_complete(messages, simulate=simulate)

    llm.complete = spy
    return sent


def test_chat_returns_contract_shape(client):
    response = chat(client, session_id="abc", message="Hello")
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {"session_id", "reply", "metadata"}
    assert body["session_id"] == "abc"
    assert body["reply"] == "reply from key_1"

    meta = body["metadata"]
    assert set(meta) == METADATA_FIELDS
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == MODEL
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 0
    assert isinstance(meta["input_tokens"], int) and meta["input_tokens"] > 0
    assert isinstance(meta["output_tokens"], int) and meta["output_tokens"] > 0


def test_history_is_saved_oldest_first(client):
    chat(client, message="first")
    chat(client, message="second")

    response = client.get("/sessions/s1/messages")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "s1"

    messages = body["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "first"
    assert messages[2]["content"] == "second"
    # user messages have no metadata key, assistant messages do
    assert "metadata" not in messages[0]
    assert set(messages[1]["metadata"]) == METADATA_FIELDS
    # the system prompt is never part of the history
    assert all(m["role"] != "system" for m in messages)


def test_full_conversation_is_sent_to_the_llm(client, sent_to_llm):
    """Every request sends: system prompt + all earlier turns + the new message."""
    chat(client, message="first")
    chat(client, message="second")

    assert sent_to_llm[1] == [
        {"role": "system", "content": DEFAULT_PROMPT},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply from key_1"},
        {"role": "user", "content": "second"},
    ]


def test_custom_system_prompt_is_used_and_remembered(client, sent_to_llm):
    chat(client, message="first", system_prompt="Talk like a pirate.")
    chat(client, message="second")  # no prompt sent -> the saved one is reused

    assert sent_to_llm[0][0] == {"role": "system", "content": "Talk like a pirate."}
    assert sent_to_llm[1][0] == {"role": "system", "content": "Talk like a pirate."}


def test_sessions_are_separate(client):
    chat(client, session_id="a", message="for a")
    chat(client, session_id="b", message="for b")
    messages = client.get("/sessions/a/messages").json()["messages"]
    assert [m["content"] for m in messages if m["role"] == "user"] == ["for a"]
