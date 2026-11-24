"""X-Simulate-Failure test hook.

The header makes chosen keys fail inside ONE request, so failover can be shown
on demand without burning real quota:

    X-Simulate-Failure: key_1=429             -> key_1 fails, key_2 answers
    X-Simulate-Failure: key_1=429,key_2=500   -> both fail -> 503
    X-Simulate-Failure: *=429                 -> every key fails -> 503

How it works:
1. /chat parses the header into a dict like {"key_1": 429}.
2. That dict is put in a ContextVar (a "global" that belongs to the current
   request only, so two requests running at the same time never mix).
3. LiteLLM's Router calls our hook right after it picks a key and BEFORE it
   calls Gemini (and before its cache is checked). If the chosen key is in
   the dict, the hook raises the same error the provider would have raised,
   and the Router moves on to the next key exactly like a real failure.
"""

from contextlib import contextmanager
from contextvars import ContextVar

import litellm
from litellm.integrations.custom_logger import CustomLogger

ALLOWED_STATUSES = {429, 500, 502, 503}

# key_id -> HTTP status to fake, for the request that is currently running
_active_failures: ContextVar[dict[str, int]] = ContextVar("active_failures", default={})


class InvalidSimulationHeader(ValueError):
    """The X-Simulate-Failure header is badly formatted."""


def parse_simulation_header(value: str | None, key_ids: list[str]) -> dict[str, int]:
    """'key_1=429, key_2=500' -> {'key_1': 429, 'key_2': 500}. '*' expands to every key."""
    if value is None or not value.strip():
        return {}

    failures: dict[str, int] = {}
    for pair in value.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key_id, sep, status_text = pair.partition("=")
        key_id, status_text = key_id.strip(), status_text.strip()

        if not sep or not status_text.isdigit():
            raise InvalidSimulationHeader(f"expected <key_id>=<status>, got '{pair}'")
        status = int(status_text)
        if status not in ALLOWED_STATUSES:
            allowed = ", ".join(str(s) for s in sorted(ALLOWED_STATUSES))
            raise InvalidSimulationHeader(f"status must be one of {allowed}, got {status}")

        if key_id == "*":
            for kid in key_ids:
                failures[kid] = status
        elif key_id in key_ids:
            failures[key_id] = status
        else:
            raise InvalidSimulationHeader(f"unknown key id '{key_id}'")
    return failures


def make_provider_error(status: int, model: str) -> Exception:
    """Build the same LiteLLM exception a real provider error with this status produces."""
    message = f"simulated {status} (X-Simulate-Failure)"
    error_classes = {
        429: litellm.RateLimitError,
        500: litellm.InternalServerError,
        502: litellm.BadGatewayError,
        503: litellm.ServiceUnavailableError,
    }
    return error_classes[status](message, llm_provider="simulated", model=model)


@contextmanager
def simulated_failures(failures: dict[str, int]):
    """Activate the failures for the code inside the `with` block (one request)."""
    token = _active_failures.set(failures)
    try:
        yield
    finally:
        _active_failures.reset(token)


class FailureSimulationHook(CustomLogger):
    """LiteLLM callback: runs after the Router picks a key, before the provider call."""

    async def async_pre_call_check(self, deployment: dict, parent_otel_span=None) -> dict | None:
        key_id = deployment.get("model_info", {}).get("id")
        status = _active_failures.get().get(key_id)
        if status is not None:
            raise make_provider_error(status, deployment["litellm_params"]["model"])
        return None
