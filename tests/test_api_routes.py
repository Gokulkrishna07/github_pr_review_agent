"""Tests for the config CRUD API endpoints."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent.agent import app
from agent.auth import _create_session_token
from agent.database import init_db, upsert_user
from agent.prompts import REVIEW_TEMPLATE


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("agent.database.settings.config_db_path", path)
    yield path
    os.unlink(path)


@pytest.fixture
async def user():
    await init_db()
    return await upsert_user(1001, "alice", "https://avatar/a", "gho_test_token")


@pytest.fixture
def auth_cookies(user):
    token = _create_session_token(
        user_id=user["id"], github_id=1001, github_login="alice"
    )
    return {"session": token}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAuthRequired:
    async def test_list_configs_requires_auth(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code == 401

    async def test_get_defaults_requires_auth(self, client):
        resp = await client.get("/api/config/defaults")
        assert resp.status_code == 401

    async def test_put_config_requires_auth(self, client):
        resp = await client.put("/api/config/owner/repo", json={"repo_full_name": "owner/repo"})
        assert resp.status_code == 401

    async def test_delete_config_requires_auth(self, client):
        resp = await client.delete("/api/config/owner/repo")
        assert resp.status_code == 401

    async def test_preview_requires_auth(self, client):
        resp = await client.post("/api/config/preview", json={"prompt_template": "x"})
        assert resp.status_code == 401

    async def test_repos_requires_auth(self, client):
        resp = await client.get("/api/repos")
        assert resp.status_code == 401


class TestGetDefaults:
    async def test_returns_default_template_and_style(self, client, auth_cookies):
        resp = await client.get("/api/config/defaults", cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["prompt_template"] == REVIEW_TEMPLATE
        assert data["output_style"]["emoji"] is True
        assert data["output_style"]["show_whats_good"] is True
        assert "critical" in data["output_style"]["severity_categories"]


class TestConfigCRUD:
    async def test_list_empty(self, client, auth_cookies, user):
        resp = await client.get("/api/config", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_config(self, client, auth_cookies, user):
        body = {
            "repo_full_name": "owner/repo",
            "prompt_template": "Custom: {filename} {patch} {pr_title} {pr_description} {file_content_section}",
            "output_style": {"emoji": False, "show_whats_good": True, "severity_categories": ["critical"], "format": "grouped", "include_line_refs": True},
            "severity_filter": ["critical", "major"],
        }
        resp = await client.put("/api/config/owner/repo", json=body, cookies=auth_cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["repo_full_name"] == "owner/repo"
        assert data["prompt_template"].startswith("Custom:")
        assert data["output_style"]["emoji"] is False
        assert data["severity_filter"] == ["critical", "major"]

    async def test_update_config(self, client, auth_cookies, user):
        body_v1 = {
            "repo_full_name": "owner/repo",
            "prompt_template": "v1 {filename} {patch} {pr_title} {pr_description} {file_content_section}",
        }
        body_v2 = {
            "repo_full_name": "owner/repo",
            "prompt_template": "v2 {filename} {patch} {pr_title} {pr_description} {file_content_section}",
        }
        await client.put("/api/config/owner/repo", json=body_v1, cookies=auth_cookies)
        resp = await client.put("/api/config/owner/repo", json=body_v2, cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["prompt_template"].startswith("v2")

    async def test_get_config(self, client, auth_cookies, user):
        body = {"repo_full_name": "owner/repo", "prompt_template": "test"}
        await client.put("/api/config/owner/repo", json=body, cookies=auth_cookies)
        resp = await client.get("/api/config/owner/repo", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["prompt_template"] == "test"

    async def test_get_config_not_found(self, client, auth_cookies, user):
        resp = await client.get("/api/config/owner/nonexistent", cookies=auth_cookies)
        assert resp.status_code == 404

    async def test_delete_config(self, client, auth_cookies, user):
        body = {"repo_full_name": "owner/repo"}
        await client.put("/api/config/owner/repo", json=body, cookies=auth_cookies)
        resp = await client.delete("/api/config/owner/repo", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    async def test_delete_config_not_found(self, client, auth_cookies, user):
        resp = await client.delete("/api/config/owner/nope", cookies=auth_cookies)
        assert resp.status_code == 404

    async def test_list_after_create(self, client, auth_cookies, user):
        body = {"repo_full_name": "owner/repo"}
        await client.put("/api/config/owner/repo", json=body, cookies=auth_cookies)
        resp = await client.get("/api/config", cookies=auth_cookies)
        assert resp.status_code == 200
        configs = resp.json()
        assert len(configs) == 1
        assert configs[0]["repo_full_name"] == "owner/repo"

    async def test_wildcard_config(self, client, auth_cookies, user):
        body = {"repo_full_name": "*", "prompt_template": "global default"}
        await client.put("/api/config/*", json=body, cookies=auth_cookies)
        # Querying a repo that has no specific config should fall back to wildcard
        resp = await client.get("/api/config/any/repo", cookies=auth_cookies)
        assert resp.status_code == 200
        assert resp.json()["prompt_template"] == "global default"


class TestPreviewPrompt:
    async def test_preview_with_default_template(self, client, auth_cookies, user):
        body = {
            "prompt_template": REVIEW_TEMPLATE,
            "filename": "test.py",
            "patch": "+ hello",
            "pr_title": "Test PR",
            "pr_description": "A test",
        }
        resp = await client.post("/api/config/preview", json=body, cookies=auth_cookies)
        assert resp.status_code == 200
        rendered = resp.json()["rendered_prompt"]
        assert "test.py" in rendered
        assert "Test PR" in rendered

    async def test_preview_with_custom_template(self, client, auth_cookies, user):
        body = {
            "prompt_template": "Review {filename} diff:\n{patch}\nPR: {pr_title}\n{pr_description}\n{file_content_section}",
            "filename": "app.py",
            "patch": "+ import os",
            "pr_title": "Add import",
            "pr_description": "",
        }
        resp = await client.post("/api/config/preview", json=body, cookies=auth_cookies)
        assert resp.status_code == 200
        rendered = resp.json()["rendered_prompt"]
        assert "Review app.py" in rendered


class TestListRepos:
    @patch("agent.api_routes.httpx.AsyncClient")
    async def test_fetches_repos(self, mock_client_cls, client, auth_cookies, user):
        mock_http = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "full_name": "alice/my-repo",
                "name": "my-repo",
                "owner": {"login": "alice"},
                "private": False,
                "description": "A test repo",
                "language": "Python",
            }
        ]
        mock_http.get = AsyncMock(return_value=mock_resp)

        resp = await client.get("/api/repos", cookies=auth_cookies)
        assert resp.status_code == 200
        repos = resp.json()
        assert len(repos) == 1
        assert repos[0]["full_name"] == "alice/my-repo"

    @patch("agent.api_routes.httpx.AsyncClient")
    async def test_github_api_failure(self, mock_client_cls, client, auth_cookies, user):
        mock_http = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_http.get = AsyncMock(return_value=mock_resp)

        resp = await client.get("/api/repos", cookies=auth_cookies)
        assert resp.status_code == 502
