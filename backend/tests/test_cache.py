"""LiteLLM response cache: the same message list is answered from memory."""

from tests.helpers import chat


def test_same_first_message_in_new_session_is_a_cache_hit(client):
    first = chat(client, session_id="a", message="What is SQLite?").json()
    second = chat(client, session_id="b", message="What is SQLite?").json()

    assert first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"]
    assert second["metadata"]["key_id"] is None
    assert second["metadata"]["fallback_attempts"] == 0
    # the tokens stored with the cached reply are returned again
    assert second["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert second["metadata"]["output_tokens"] == first["metadata"]["output_tokens"]


def test_cache_hit_is_saved_in_history(client):
    chat(client, session_id="a", message="hi")
    chat(client, session_id="b", message="hi")
    messages = client.get("/sessions/b/messages").json()["messages"]
    assert messages[1]["metadata"]["resolution_source"] == "LLM_CACHE"
    assert messages[1]["metadata"]["key_id"] is None


def test_cache_hit_does_not_call_any_key(client):
    """key_1 is made to fail, yet the answer is key_1's old reply -> no key was called
    (a live call would have fallen back to key_2 and said 'reply from key_2')."""
    first = chat(client, session_id="a", message="cache me").json()
    second = chat(
        client, session_id="b", message="cache me", headers={"X-Simulate-Failure": "key_1=429"}
    ).json()
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"] == "reply from key_1"


def test_star_429_is_503_even_for_a_cached_message(client):
    """The simulated failure runs before the cache is checked: *=429 always means 503."""
    chat(client, session_id="a", message="cached question")
    response = chat(
        client, session_id="b", message="cached question", headers={"X-Simulate-Failure": "*=429"}
    )
    assert response.status_code == 503
    assert client.get("/sessions/b/messages").status_code == 404


def test_reply_from_fallback_key_is_cached_too(client):
    """caching_groups: a reply key_2 gave is found again when we ask key_1."""
    chat(client, session_id="a", message="q", headers={"X-Simulate-Failure": "key_1=429"})
    second = chat(client, session_id="b", message="q").json()
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == "reply from key_2"


def test_different_system_prompt_is_a_miss(client):
    chat(client, session_id="a", message="hi", system_prompt="Be short.")
    second = chat(client, session_id="b", message="hi", system_prompt="Be long.").json()
    assert second["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_different_history_is_a_miss(client):
    """The cache key is the FULL message list, not just the last message."""
    chat(client, session_id="a", message="hi")
    chat(client, session_id="b", message="something else first")
    second_turn = chat(client, session_id="b", message="hi").json()
    assert second_turn["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_later_turns_are_cached_too(client):
    """max_messages=None: turns with more than 4 messages in the list are cached as well."""
    for session in ("a", "b"):
        results = [chat(client, session_id=session, message=f"turn {i}").json() for i in range(3)]
    # session b repeats session a turn by turn -> every turn is a hit
    assert [r["metadata"]["resolution_source"] for r in results] == ["LLM_CACHE"] * 3


def test_cache_starts_empty_in_every_test(client):
    """Same message as the first test, but the fixture flushed the cache -> live."""
    response = chat(client, session_id="a", message="What is SQLite?").json()
    assert response["metadata"]["resolution_source"] == "LIVE_INFERENCE"
