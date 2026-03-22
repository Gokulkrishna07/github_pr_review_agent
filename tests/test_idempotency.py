import pytest

import agent.idempotency as idempotency_module
from agent.idempotency import is_already_reviewed, mark_as_reviewed


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    """Redirect the SQLite DB to a fresh temp file for every test."""
    db_file = str(tmp_path / "reviews_test.db")
    monkeypatch.setattr(idempotency_module, "_DB_PATH", db_file)
    yield db_file


class TestIsAlreadyReviewed:
    async def test_fresh_db_returns_false(self):
        assert await is_already_reviewed("owner", "repo", 1, "abc123") is False

    async def test_after_mark_returns_true(self):
        await mark_as_reviewed("owner", "repo", 1, "abc123")
        assert await is_already_reviewed("owner", "repo", 1, "abc123") is True

    async def test_different_commit_sha_not_duplicate(self):
        await mark_as_reviewed("owner", "repo", 1, "sha-old")
        assert await is_already_reviewed("owner", "repo", 1, "sha-new") is False

    async def test_different_pr_number_not_duplicate(self):
        await mark_as_reviewed("owner", "repo", 1, "sha")
        assert await is_already_reviewed("owner", "repo", 2, "sha") is False

    async def test_different_repo_same_owner_not_duplicate(self):
        await mark_as_reviewed("owner", "repo-a", 1, "sha")
        assert await is_already_reviewed("owner", "repo-b", 1, "sha") is False

    async def test_different_owner_not_duplicate(self):
        await mark_as_reviewed("owner-a", "repo", 1, "sha")
        assert await is_already_reviewed("owner-b", "repo", 1, "sha") is False


class TestMarkAsReviewed:
    async def test_marking_same_entry_twice_does_not_raise(self):
        await mark_as_reviewed("owner", "repo", 1, "sha")
        # Second call should not raise due to INSERT OR IGNORE
        await mark_as_reviewed("owner", "repo", 1, "sha")
        assert await is_already_reviewed("owner", "repo", 1, "sha") is True

    async def test_multiple_distinct_reviews_stored_independently(self):
        await mark_as_reviewed("owner", "repo", 1, "sha-1")
        await mark_as_reviewed("owner", "repo", 2, "sha-2")
        await mark_as_reviewed("owner", "repo-b", 1, "sha-1")
        await mark_as_reviewed("owner-x", "repo", 1, "sha-1")

        assert await is_already_reviewed("owner", "repo", 1, "sha-1") is True
        assert await is_already_reviewed("owner", "repo", 2, "sha-2") is True
        assert await is_already_reviewed("owner", "repo-b", 1, "sha-1") is True
        assert await is_already_reviewed("owner-x", "repo", 1, "sha-1") is True

        # Cross-combinations that were never marked should still be False
        assert await is_already_reviewed("owner", "repo", 2, "sha-1") is False
        assert await is_already_reviewed("owner", "repo-b", 2, "sha-2") is False

    async def test_mark_creates_table_implicitly(self):
        # Verifies that calling mark before is works (table auto-created on first _conn()).
        await mark_as_reviewed("newowner", "newrepo", 99, "newsha")
        assert await is_already_reviewed("newowner", "newrepo", 99, "newsha") is True
