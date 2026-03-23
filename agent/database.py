"""Async SQLite database layer for user accounts and review configurations."""

from __future__ import annotations

import json
import logging
import os

import aiosqlite

from .config import settings

logger = logging.getLogger(__name__)

_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    github_id     INTEGER UNIQUE NOT NULL,
    github_login  TEXT NOT NULL,
    avatar_url    TEXT DEFAULT '',
    access_token  TEXT NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_REVIEW_CONFIGS = """
CREATE TABLE IF NOT EXISTS review_configs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    repo_full_name  TEXT NOT NULL,
    prompt_template TEXT,
    output_style    TEXT NOT NULL DEFAULT '{}',
    severity_filter TEXT NOT NULL DEFAULT '["critical","major","minor","nit"]',
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    llm_provider    TEXT NOT NULL DEFAULT 'groq',
    llm_model       TEXT,
    UNIQUE(user_id, repo_full_name)
)
"""

_MIGRATIONS = [
    "ALTER TABLE review_configs ADD COLUMN llm_provider TEXT NOT NULL DEFAULT 'groq'",
    "ALTER TABLE review_configs ADD COLUMN llm_model TEXT",
]


def _db_path() -> str:
    return settings.config_db_path


async def _get_db() -> aiosqlite.Connection:
    path = _db_path()
    if path != ":memory:":
        os.makedirs(os.path.dirname(path), exist_ok=True)
    db = await aiosqlite.connect(path)
    try:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
    except Exception:
        await db.close()
        raise
    return db


async def init_db() -> None:
    db = await _get_db()
    try:
        await db.execute(_CREATE_USERS)
        await db.execute(_CREATE_REVIEW_CONFIGS)
        # Run migrations for existing databases (idempotent)
        for sql in _MIGRATIONS:
            try:
                await db.execute(sql)
            except Exception:
                pass  # Column already exists
        await db.commit()
        logger.info("Config database initialized at %s", _db_path())
    finally:
        await db.close()


async def upsert_user(
    github_id: int, github_login: str, avatar_url: str, access_token: str
) -> dict:
    db = await _get_db()
    try:
        await db.execute(
            """INSERT INTO users (github_id, github_login, avatar_url, access_token)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(github_id) DO UPDATE SET
                 github_login = excluded.github_login,
                 avatar_url = excluded.avatar_url,
                 access_token = excluded.access_token,
                 updated_at = CURRENT_TIMESTAMP""",
            (github_id, github_login, avatar_url, access_token),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM users WHERE github_id = ?", (github_id,)
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


async def get_user_by_github_id(github_id: int) -> dict | None:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM users WHERE github_id = ?", (github_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_user_by_id(user_id: int) -> dict | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def upsert_review_config(
    user_id: int,
    repo_full_name: str,
    prompt_template: str | None = None,
    output_style: dict | None = None,
    severity_filter: list[str] | None = None,
    llm_provider: str = "groq",
    llm_model: str | None = None,
    active: bool = True,
) -> dict:
    if not user_id or not repo_full_name:
        raise ValueError("user_id and repo_full_name are required")
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive integer")

    output_style_json = json.dumps(output_style or {})
    severity_filter_json = json.dumps(
        severity_filter or ["critical", "major", "minor", "nit"]
    )
    db = await _get_db()
    try:
        await db.execute(
            """INSERT INTO review_configs
                 (user_id, repo_full_name, prompt_template, output_style,
                  severity_filter, llm_provider, llm_model, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, repo_full_name) DO UPDATE SET
                 prompt_template = excluded.prompt_template,
                 output_style = excluded.output_style,
                 severity_filter = excluded.severity_filter,
                 llm_provider = excluded.llm_provider,
                 llm_model = excluded.llm_model,
                 active = excluded.active,
                 updated_at = CURRENT_TIMESTAMP""",
            (user_id, repo_full_name, prompt_template, output_style_json,
             severity_filter_json, llm_provider, llm_model, int(active)),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM review_configs WHERE user_id = ? AND repo_full_name = ?",
            (user_id, repo_full_name),
        )
        row = await cursor.fetchone()
        return _deserialize_config(dict(row))
    finally:
        await db.close()


async def get_review_config(user_id: int, repo_full_name: str) -> dict | None:
    db = await _get_db()
    try:
        # Try repo-specific config first
        cursor = await db.execute(
            "SELECT * FROM review_configs WHERE user_id = ? AND repo_full_name = ? AND active = 1",
            (user_id, repo_full_name),
        )
        row = await cursor.fetchone()
        if row:
            return _deserialize_config(dict(row))

        # Fall back to wildcard default
        cursor = await db.execute(
            "SELECT * FROM review_configs WHERE user_id = ? AND repo_full_name = '*' AND active = 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return _deserialize_config(dict(row)) if row else None
    finally:
        await db.close()


async def get_config_for_repo(owner: str, repo: str) -> dict | None:
    """Look up review config for a repo across all users. Used by the webhook pipeline."""
    repo_full_name = f"{owner}/{repo}"
    db = await _get_db()
    try:
        # Try repo-specific config from any user
        cursor = await db.execute(
            "SELECT * FROM review_configs WHERE repo_full_name = ? AND active = 1 LIMIT 1",
            (repo_full_name,),
        )
        row = await cursor.fetchone()
        if row:
            return _deserialize_config(dict(row))

        # Fall back to wildcard from any user
        cursor = await db.execute(
            "SELECT * FROM review_configs WHERE repo_full_name = '*' AND active = 1 LIMIT 1",
        )
        row = await cursor.fetchone()
        return _deserialize_config(dict(row)) if row else None
    finally:
        await db.close()


async def list_user_configs(user_id: int) -> list[dict]:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM review_configs WHERE user_id = ? ORDER BY repo_full_name",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [_deserialize_config(dict(r)) for r in rows]
    finally:
        await db.close()


async def delete_review_config(user_id: int, repo_full_name: str) -> bool:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM review_configs WHERE user_id = ? AND repo_full_name = ?",
            (user_id, repo_full_name),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


def _deserialize_config(row: dict) -> dict:
    """Parse JSON fields in a review_configs row."""
    row["output_style"] = json.loads(row.get("output_style") or "{}")
    row["severity_filter"] = json.loads(
        row.get("severity_filter") or '["critical","major","minor","nit"]'
    )
    row["active"] = bool(row.get("active", 1))
    return row
