"""Application settings, read once from environment variables."""

import os
from dataclasses import dataclass


def _split_csv(value: str) -> list[str]:
    """'a, b,,c' -> ['a', 'b', 'c']"""
    return [item.strip() for item in value.split(",") if item.strip()]


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_keys: list[str]
    model: str
    database_url: str
    allowed_origins: list[str]
    enable_failure_simulation: bool
    default_system_prompt: str
    llm_timeout_seconds: float

    @property
    def key_ids(self) -> list[str]:
        """Public ids for the key pool: key_1, key_2, ... (never the key itself)."""
        return [f"key_{i}" for i in range(1, len(self.api_keys) + 1)]

    @property
    def database_path(self) -> str:
        """'sqlite:////data/app.db' -> '/data/app.db', 'sqlite:///./app.db' -> './app.db'"""
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("DATABASE_URL must start with 'sqlite:///'")
        return self.database_url[len(prefix):]


def load_settings() -> Settings:
    env = os.environ
    return Settings(
        api_keys=_split_csv(env.get("LLM_API_KEYS", "")),
        model=env.get("LLM_MODEL", "gemini/gemini-2.5-flash"),
        database_url=env.get("DATABASE_URL", "sqlite:///./data/app.db"),
        allowed_origins=_split_csv(env.get("ALLOWED_ORIGINS", "http://localhost:3000")),
        enable_failure_simulation=_to_bool(env.get("ENABLE_FAILURE_SIMULATION", "false")),
        default_system_prompt=env.get(
            "DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant."
        ),
        llm_timeout_seconds=float(env.get("LLM_TIMEOUT_SECONDS", "30")),
    )
