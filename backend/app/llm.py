"""LLM gateway: a LiteLLM Router over a pool of Gemini API keys.

Each key becomes its own Router "model group" named after its public id
(key_1, key_2, ...). We always ask for key_1 and tell the Router to fall back
to key_2, key_3, ... in order. So:

    key_1 fails (429 / quota / 5xx / timeout)  ->  Router retries the same
    messages on key_2  ->  ...  ->  every key failed  ->  AllProvidersFailed (503)

The Router tells us which key answered (response._hidden_params["model_id"])
and how many fallbacks it needed (the "x-litellm-attempted-fallbacks" header),
so we never have to write the retry loop ourselves.
"""

import logging
from dataclasses import dataclass

import litellm
from litellm import Router

from app.config import Settings
from app.simulate import FailureSimulationHook, simulated_failures

logger = logging.getLogger("app.llm")

litellm.suppress_debug_info = True  # keep LiteLLM's "Give Feedback" banners out of our logs
logging.getLogger("LiteLLM").setLevel(logging.WARNING)  # it logs every call at INFO

# One hook for the whole process (litellm.callbacks is global)
_simulation_hook = FailureSimulationHook()


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


def build_router(settings: Settings) -> Router:
    """One deployment per key; fallback chain key_1 -> key_2 -> ... -> key_N."""
    key_ids = settings.key_ids
    model_list = [
        {
            "model_name": key_id,  # the group name we route to
            "litellm_params": {
                "model": settings.model,
                "api_key": api_key,  # stays inside the Router, never logged or returned
                "timeout": settings.llm_timeout_seconds,
            },
            "model_info": {"id": key_id},  # comes back as response._hidden_params["model_id"]
        }
        for key_id, api_key in zip(key_ids, settings.api_keys)
    ]
    return Router(
        model_list=model_list,
        fallbacks=[{key_ids[0]: key_ids[1:]}] if len(key_ids) > 1 else [],
        num_retries=0,  # don't retry the SAME key; move to the next one instead
        disable_cooldowns=True,  # a (simulated) failure must not bench a key for later requests
    )


class LLMGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache_enabled = False  # LiteLLM cache is switched on in Step 5
        self.router = build_router(settings) if settings.api_keys else None
        if _simulation_hook not in litellm.callbacks:
            litellm.callbacks.append(_simulation_hook)

    async def complete(
        self, messages: list[dict], simulate: dict[str, int] | None = None
    ) -> LLMResult:
        """Send the full message list to the key pool. `simulate` = {key_id: status} to fake."""
        if self.router is None:
            raise AllProvidersFailed("no API keys configured")

        first_key = self.settings.key_ids[0]
        try:
            with simulated_failures(simulate or {}):
                response = await self.router.acompletion(model=first_key, messages=messages)
        except Exception as error:
            # The Router only raises after the last key failed too
            logger.warning(
                "All keys failed, last error: %s (status %s)",
                type(error).__name__,
                getattr(error, "status_code", "?"),
            )
            raise AllProvidersFailed() from error

        reply = (response.choices[0].message.content or "").strip()
        if not reply:
            # Never return an empty answer as a success
            logger.warning("Provider returned an empty reply")
            raise AllProvidersFailed()

        hidden = response._hidden_params or {}
        key_id = hidden.get("model_id")
        headers = hidden.get("additional_headers") or {}
        fallback_attempts = int(headers.get("x-litellm-attempted-fallbacks") or 0)
        if fallback_attempts:
            logger.info("Answered by %s after %d failed key(s)", key_id, fallback_attempts)

        usage = response.usage
        return LLMResult(
            reply=reply,
            model=self.settings.model,
            resolution_source="LIVE_INFERENCE",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            key_id=key_id,
            fallback_attempts=fallback_attempts,
        )
