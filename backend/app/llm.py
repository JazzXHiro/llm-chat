"""LLM gateway.

TEMPORARY STUB (Step 2): echoes the user's message so the API can be built and
tested without calling a real model. Replaced by the LiteLLM Router in Step 4.
"""

from dataclasses import dataclass

from app.config import Settings


class AllProvidersFailed(Exception):
    """Raised when every key in the pool failed for this request."""


@dataclass
class LLMResult:
    reply: str
    model: str
    resolution_source: str  # "LIVE_INFERENCE" or "LLM_CACHE"
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


class LLMGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache_enabled = False  # real cache arrives in Step 5

    async def complete(self, messages: list[dict]) -> LLMResult:
        user_text = messages[-1]["content"]
        reply = f"(stub) You said: {user_text}"
        prompt_words = sum(len(m["content"].split()) for m in messages)
        return LLMResult(
            reply=reply,
            model="stub-model",
            resolution_source="LIVE_INFERENCE",
            input_tokens=prompt_words,
            output_tokens=len(reply.split()),
            key_id="key_1",
            fallback_attempts=0,
        )
