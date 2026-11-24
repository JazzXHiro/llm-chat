"""SQLite storage for chat sessions, using Python's built-in sqlite3 module."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT,                -- custom prompt for this session, NULL = default
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    metadata    TEXT,                  -- JSON string, assistant messages only
    created_at  TEXT NOT NULL          -- server time, ISO-8601
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, id);
"""


def utc_now() -> str:
    """Current server time as ISO-8601, e.g. 2026-11-24T12:01:42.123+00:00"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Database:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def _connect(self):
        """Open a connection, commit on success, roll back on error, always close."""
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row  # rows behave like dicts: row["content"]
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        """Create the folder, tables and index if they don't exist (runs at startup)."""
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
            conn.executescript(SCHEMA)

    def ping(self) -> bool:
        """True if the database answers a trivial query (used by /health)."""
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def get_system_prompt(self, session_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row["system_prompt"] if row else None

    def get_history(self, session_id: str) -> list[dict]:
        """All messages of a session, oldest first. Metadata only on assistant messages."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        history = []
        for row in rows:
            message = {"role": row["role"], "content": row["content"]}
            if row["metadata"]:
                message["metadata"] = json.loads(row["metadata"])
            history.append(message)
        return history

    def save_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_reply: str,
        metadata: dict,
        system_prompt: str | None,
        user_created_at: str,
    ) -> None:
        """Store one successful exchange (user + assistant) in a single transaction."""
        with self._connect() as conn:
            # Create the session on first use; only overwrite the prompt if a new one was sent
            conn.execute(
                """
                INSERT INTO sessions (session_id, system_prompt, created_at) VALUES (?, ?, ?)
                ON CONFLICT (session_id) DO UPDATE
                SET system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt)
                """,
                (session_id, system_prompt, user_created_at),
            )
            conn.executemany(
                "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (session_id, "user", user_message, None, user_created_at),
                    (session_id, "assistant", assistant_reply, json.dumps(metadata), utc_now()),
                ],
            )
