"""FastAPI application: routes, CORS and error handling."""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, load_settings
from app.db import Database, utc_now
from app.llm import AllProvidersFailed, LLMGateway
from app.schemas import (
    ChatMetadata,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    HistoryResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request):
    state = request.app.state
    if not state.settings.api_keys:
        raise HTTPException(status_code=503, detail="no API keys configured")
    if not state.db.ping():
        raise HTTPException(status_code=503, detail="database unavailable")
    return HealthResponse(
        status="ok",
        keys_configured=len(state.settings.api_keys),
        cache_enabled=state.llm.cache_enabled,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request):
    start = time.perf_counter()
    received_at = utc_now()
    state = request.app.state
    db: Database = state.db

    # Prompt priority: sent now > saved for this session > default from env
    system_prompt = (
        body.system_prompt
        or db.get_system_prompt(body.session_id)
        or state.settings.default_system_prompt
    )
    history = db.get_history(body.session_id)  # unknown session -> [] -> new session

    # Full message list sent to the LLM: system + earlier turns + new message
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": body.message})

    try:
        result = await state.llm.complete(messages)
    except AllProvidersFailed:
        # Nothing is stored for a failed request
        raise HTTPException(status_code=503, detail="all providers unavailable")

    metadata = ChatMetadata(
        resolution_source=result.resolution_source,
        model=result.model,
        latency_ms=round((time.perf_counter() - start) * 1000),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        key_id=result.key_id,
        fallback_attempts=result.fallback_attempts,
    )

    # Save the user message and the reply together, only after success
    db.save_turn(
        session_id=body.session_id,
        user_message=body.message,
        assistant_reply=result.reply,
        metadata=metadata.model_dump(),
        system_prompt=body.system_prompt or None,
        user_created_at=received_at,
    )

    return ChatResponse(session_id=body.session_id, reply=result.reply, metadata=metadata)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=HistoryResponse,
    response_model_exclude_none=True,  # user messages have no "metadata" key
)
async def get_history(session_id: str, request: Request):
    history = request.app.state.db.get_history(session_id)
    if not history:
        raise HTTPException(status_code=404, detail="session not found")
    return HistoryResponse(session_id=session_id, messages=history)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Runs once at startup
        app.state.settings = settings
        app.state.db = Database(settings.database_path)
        app.state.db.init()  # creates tables on startup
        app.state.llm = LLMGateway(settings)
        logger.info("Started with %d key(s), model=%s", len(settings.api_keys), settings.model)
        yield

    app = FastAPI(title="Lyftr Chat API", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def catch_unhandled_errors(request: Request, call_next):
        # Last line of defence: never leak a stack trace or an HTML error page
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content={"detail": "internal server error"})

    # Added after the error middleware so CORS headers are on error responses too
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()
