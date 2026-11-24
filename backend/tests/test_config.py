"""Settings parsing from environment variables."""

from app.config import load_settings


def test_allowed_origins_are_split_and_trailing_slash_removed(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://chat.vercel.app/ ,http://localhost:3000,,")
    settings = load_settings()
    assert settings.allowed_origins == ["https://chat.vercel.app", "http://localhost:3000"]
