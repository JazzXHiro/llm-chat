"""LLM gateway: a LiteLLM Router over a pool of Gemini API keys.

Each key becomes its own Router "model group" named after its public id
(key_1, key_2, ...). We always ask for key_1 and tell the Router to fall back
to key_2, key_3, ... in order. So:

    key_1 fails (429 / quota / 5xx / timeout)  ->  Router retries the same
    messages on key_2  ->  ...  ->  every key failed  ->  AllProvidersFailed (503)

The Router tells us which key answered (response._hidden_params["model_id"])
and how many fallbacks it needed (the "x-litellm-attempted-fallbacks" header),
so we never have to write the retry loop ourselves.

Caching: LiteLLM's built-in in-memory cache sits in front of the keys. The
cache key is the model + the full message list (system prompt and history
included), so the same conversation asked again is answered from memory
without calling Gemini: resolution_source = LLM_CACHE, key_id = None.
"""

import asyncio
import logging
from dataclasses import dataclass

import litellm
from litellm import Router
from litellm.caching.caching import Cache
from litellm.caching.caching_handler import _PENDING_CACHE_WRITES

from app.config import Settings
from app.simulate import FailureSimulationHook, simulated_failures

logger = logging.getLogger("app.llm")

litellm.suppress_debug_info = True  # keep LiteLLM's "Give Feedback" banners out of our logs
logging.getLogger("LiteLLM").setLevel(logging.WARNING)  # it logs every call at INFO

# One hook for the whole process (litellm.callbacks is global)
_simulation_hook = FailureSimulationHook()

CACHE_TTL_SECONDS = 3600  # a cached reply is reused for 1 hour


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
        cache_responses=True,
        # By default the cache key contains the model GROUP name (key_1 or key_2),
        # so a reply that came from key_2 after a fallback would never be found
        # when we ask key_1 again. One caching group = all keys share one cache.
        caching_groups=[tuple(key_ids)],
    )


def setup_cache() -> None:
    """Switch on LiteLLM's in-memory cache (process-wide, like litellm.callbacks)."""
    litellm.cache = Cache(
        type="local",
        ttl=CACHE_TTL_SECONDS,
        # LiteLLM skips the cache for requests with more than 4 messages by
        # default; we want EVERY conversation length cached (full-list key).
        max_messages=None,
    )


async def wait_for_cache_writes() -> None:
    """LiteLLM saves a reply into the cache in a background task AFTER returning it.

    We wait for that task, so an identical request sent right after this one
    is already a cache hit (otherwise the first repeat could still miss).
    """
    pending = list(_PENDING_CACHE_WRITES)
    if pending:
        await asyncio.wait(pending, timeout=2)


class LLMGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        setup_cache()
        self.cache_enabled = litellm.cache is not None
        self.router = build_router(settings) if settings.api_keys else None
        if _simulation_hook not in litellm.callbacks:
            litellm.callbacks.append(_simulation_hook)

    async def warm_up(self) -> None:
        """Make one fake call + cache hit at startup, then empty the cache.

        The first cache hit makes LiteLLM import heavy modules (numpy, soundfile,
        orjson), which took ~600 ms. Doing it here keeps real cache hits fast.
        mock_response means no request is sent to Gemini and no quota is used.
        """
        if self.router is None:
            return
        messages = [{"role": "user", "content": "warm-up"}]
        first_key = self.settings.key_ids[0]
        try:
            for _ in range(2):  # 1st call fills the cache, 2nd call reads it
                await self.router.acompletion(
                    model=first_key, messages=messages, mock_response="ok"
                )
                await wait_for_cache_writes()
        except Exception:
            logger.warning("Cache warm-up failed (not fatal)", exc_info=True)
        finally:
            # The mock reply must never be served to a real user
            litellm.cache.cache.flush_cache()

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
        usage = response.usage  # on a cache hit: the tokens stored with the cached reply

        if hidden.get("cache_hit"):
            # No key was called, so no key answered and no fallback happened.
            # (The Router still fills model_id / fallbacks with the path it took.)
            source, key_id, fallback_attempts = "LLM_CACHE", None, 0
        else:
            source = "LIVE_INFERENCE"
            key_id = hidden.get("model_id")
            headers = hidden.get("additional_headers") or {}
            fallback_attempts = int(headers.get("x-litellm-attempted-fallbacks") or 0)
            if fallback_attempts:
                logger.info("Answered by %s after %d failed key(s)", key_id, fallback_attempts)
            await wait_for_cache_writes()

        return LLMResult(
            reply=reply,
            model=self.settings.model,
            resolution_source=source,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            key_id=key_id,
            fallback_attempts=fallback_attempts,
        )
