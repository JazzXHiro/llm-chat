"""Request / response models. Field names follow the API contract exactly."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, StringConstraints

# Whitespace is trimmed first, then the length rule is checked.
SessionId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
SystemPrompt = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]

ResolutionSource = Literal["LIVE_INFERENCE", "LLM_CACHE"]


class ChatRequest(BaseModel):
    session_id: SessionId
    message: Message
    system_prompt: SystemPrompt | None = None


class ChatMetadata(BaseModel):
    resolution_source: ResolutionSource
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    metadata: dict[str, Any] | None = None  # assistant messages only


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


class HealthResponse(BaseModel):
    status: str
    keys_configured: int
    cache_enabled: bool
