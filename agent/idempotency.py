import os
import sqlite3

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


def is_already_reviewed(owner: str, repo: str, pr_number: int, commit_sha: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_reviews WHERE owner=? AND repo=? AND pr_number=? AND commit_sha=?",
            (owner, repo, pr_number, commit_sha),
        ).fetchone()
        return row is not None


def mark_as_reviewed(owner: str, repo: str, pr_number: int, commit_sha: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_reviews (owner, repo, pr_number, commit_sha) VALUES (?,?,?,?)",
            (owner, repo, pr_number, commit_sha),
        )
        conn.commit()
