"""Tests for the async SQLite database layer (users + review configs)."""

import os
import tempfile
from unittest.mock import patch

import pytest

from agent.database import (
    delete_review_config,
    get_config_for_repo,
    get_review_config,
    get_user_by_github_id,
    get_user_by_id,
    init_db,
    list_user_configs,
    upsert_review_config,
    upsert_user,
)


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch):
    """Redirect the config database to a temp file for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("agent.database.settings.config_db_path", path)
    yield path
    os.unlink(path)


class TestInitDb:
    async def test_creates_tables(self):
        await init_db()
        # Verify by inserting — would fail if tables don't exist
        user = await upsert_user(1001, "alice", "https://avatar.example/a", "tok_a")
        assert user["github_login"] == "alice"

    async def test_idempotent(self):
        await init_db()
        await init_db()  # Should not raise


class TestUsers:
    async def test_upsert_creates_user(self):
        await init_db()
        user = await upsert_user(1001, "alice", "https://avatar/a", "tok_a")
        assert user["github_id"] == 1001
        assert user["github_login"] == "alice"
        assert user["avatar_url"] == "https://avatar/a"
        assert user["access_token"] == "tok_a"
        assert user["id"] is not None

    async def test_upsert_updates_existing_user(self):
        await init_db()
        u1 = await upsert_user(1001, "alice", "", "tok_old")
        u2 = await upsert_user(1001, "alice-renamed", "https://new", "tok_new")
        assert u1["id"] == u2["id"]
        assert u2["github_login"] == "alice-renamed"
        assert u2["access_token"] == "tok_new"

    async def test_get_user_by_github_id_found(self):
        await init_db()
        await upsert_user(1001, "alice", "", "tok")
        user = await get_user_by_github_id(1001)
        assert user is not None
        assert user["github_login"] == "alice"

    async def test_get_user_by_github_id_not_found(self):
        await init_db()
        user = await get_user_by_github_id(9999)
        assert user is None

    async def test_get_user_by_id_found(self):
        await init_db()
        created = await upsert_user(1001, "alice", "", "tok")
        user = await get_user_by_id(created["id"])
        assert user is not None
        assert user["github_id"] == 1001

    async def test_get_user_by_id_not_found(self):
        await init_db()
        user = await get_user_by_id(9999)
        assert user is None


class TestReviewConfigs:
    async def _setup_user(self) -> dict:
        await init_db()
        return await upsert_user(1001, "alice", "", "tok")

    async def test_upsert_creates_config(self):
        user = await self._setup_user()
        config = await upsert_review_config(
            user["id"], "owner/repo",
            prompt_template="Custom prompt: {filename} {patch} {pr_title} {pr_description} {file_content_section}",
            output_style={"emoji": False},
            severity_filter=["critical", "major"],
        )
        assert config["repo_full_name"] == "owner/repo"
        assert config["prompt_template"].startswith("Custom prompt:")
        assert config["output_style"] == {"emoji": False}
        assert config["severity_filter"] == ["critical", "major"]
        assert config["active"] is True

    async def test_upsert_updates_existing(self):
        user = await self._setup_user()
        c1 = await upsert_review_config(user["id"], "owner/repo", prompt_template="v1")
        c2 = await upsert_review_config(user["id"], "owner/repo", prompt_template="v2")
        assert c1["id"] == c2["id"]
        assert c2["prompt_template"] == "v2"

    async def test_get_review_config_repo_specific(self):
        user = await self._setup_user()
        await upsert_review_config(user["id"], "owner/repo", prompt_template="specific")
        config = await get_review_config(user["id"], "owner/repo")
        assert config is not None
        assert config["prompt_template"] == "specific"

    async def test_get_review_config_falls_back_to_wildcard(self):
        user = await self._setup_user()
        await upsert_review_config(user["id"], "*", prompt_template="default")
        config = await get_review_config(user["id"], "owner/other-repo")
        assert config is not None
        assert config["prompt_template"] == "default"
        assert config["repo_full_name"] == "*"

    async def test_get_review_config_prefers_specific_over_wildcard(self):
        user = await self._setup_user()
        await upsert_review_config(user["id"], "*", prompt_template="default")
        await upsert_review_config(user["id"], "owner/repo", prompt_template="specific")
        config = await get_review_config(user["id"], "owner/repo")
        assert config["prompt_template"] == "specific"

    async def test_get_review_config_returns_none(self):
        user = await self._setup_user()
        config = await get_review_config(user["id"], "owner/repo")
        assert config is None

    async def test_get_review_config_ignores_inactive(self):
        user = await self._setup_user()
        await upsert_review_config(
            user["id"], "owner/repo", prompt_template="disabled", active=False
        )
        config = await get_review_config(user["id"], "owner/repo")
        assert config is None

    async def test_list_user_configs(self):
        user = await self._setup_user()
        await upsert_review_config(user["id"], "a/repo1")
        await upsert_review_config(user["id"], "b/repo2")
        configs = await list_user_configs(user["id"])
        assert len(configs) == 2
        names = [c["repo_full_name"] for c in configs]
        assert "a/repo1" in names
        assert "b/repo2" in names

    async def test_list_user_configs_empty(self):
        user = await self._setup_user()
        configs = await list_user_configs(user["id"])
        assert configs == []

    async def test_delete_config_exists(self):
        user = await self._setup_user()
        await upsert_review_config(user["id"], "owner/repo")
        deleted = await delete_review_config(user["id"], "owner/repo")
        assert deleted is True
        config = await get_review_config(user["id"], "owner/repo")
        assert config is None

    async def test_delete_config_not_found(self):
        user = await self._setup_user()
        deleted = await delete_review_config(user["id"], "nonexistent/repo")
        assert deleted is False


class TestGetConfigForRepo:
    async def _setup(self) -> dict:
        await init_db()
        return await upsert_user(1001, "alice", "", "tok")

    async def test_finds_repo_specific_config(self):
        user = await self._setup()
        await upsert_review_config(user["id"], "owner/repo", prompt_template="found")
        config = await get_config_for_repo("owner", "repo")
        assert config is not None
        assert config["prompt_template"] == "found"

    async def test_falls_back_to_wildcard(self):
        user = await self._setup()
        await upsert_review_config(user["id"], "*", prompt_template="wildcard")
        config = await get_config_for_repo("owner", "repo")
        assert config is not None
        assert config["prompt_template"] == "wildcard"

    async def test_returns_none_when_no_config(self):
        await self._setup()
        config = await get_config_for_repo("owner", "repo")
        assert config is None
