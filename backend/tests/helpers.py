"""Constants and small helpers shared by the test files."""

FAKE_KEYS = ["fake-key-1", "fake-key-2"]  # never real keys: nothing is sent anywhere
MODEL = "gemini/test-model"
DEFAULT_PROMPT = "You are a test assistant."

# Strings LiteLLM's mock_response turns into a real provider error
RATE_LIMIT_ERROR = "litellm.RateLimitError"  # like a 429 from Gemini
SERVER_ERROR = "litellm.InternalServerError"  # like a 500 from Gemini


def default_reply(key_id: str) -> str:
    """What a key answers when a test doesn't say otherwise."""
    return f"reply from {key_id}"


def chat(client, session_id="s1", message="Hello", headers=None, **extra):
    """POST /chat and return the response."""
    body = {"session_id": session_id, "message": message, **extra}
    return client.post("/chat", json=body, headers=headers or {})
