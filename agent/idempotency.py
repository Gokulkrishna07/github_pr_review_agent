import asyncio
import logging
import os
import sqlite3

from .exceptions import IdempotencyError

logger = logging.getLogger(__name__)

_DB_PATH = os.environ.get("IDEMPOTENCY_DB_PATH", "/app/data/reviews.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_reviews (
            owner       TEXT,
            repo        TEXT,
            pr_number   INTEGER,
            commit_sha  TEXT,
            reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (owner, repo, pr_number, commit_sha)
        )
        """
    )
    conn.commit()
    return conn


def _is_already_reviewed_sync(owner: str, repo: str, pr_number: int, commit_sha: str) -> bool:
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_reviews WHERE owner=? AND repo=? AND pr_number=? AND commit_sha=?",
                (owner, repo, pr_number, commit_sha),
            ).fetchone()
            return row is not None
    except sqlite3.Error as e:
        raise IdempotencyError(f"Failed to check review status: {e}") from e


def _mark_as_reviewed_sync(owner: str, repo: str, pr_number: int, commit_sha: str) -> None:
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_reviews (owner, repo, pr_number, commit_sha) VALUES (?,?,?,?)",
                (owner, repo, pr_number, commit_sha),
            )
            conn.commit()
    except sqlite3.Error as e:
        raise IdempotencyError(f"Failed to mark review: {e}") from e


async def is_already_reviewed(owner: str, repo: str, pr_number: int, commit_sha: str) -> bool:
    return await asyncio.to_thread(_is_already_reviewed_sync, owner, repo, pr_number, commit_sha)


async def mark_as_reviewed(owner: str, repo: str, pr_number: int, commit_sha: str) -> None:
    await asyncio.to_thread(_mark_as_reviewed_sync, owner, repo, pr_number, commit_sha)
