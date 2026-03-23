"""Tests for GitHub OAuth authentication and JWT session management."""

import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
import httpx
from httpx import ASGITransport, AsyncClient

from agent.auth import (
    _JWT_ALGORITHM,
    _JWT_EXPIRY_SECONDS,
    _create_session_token,
    decode_session_token,
    get_current_user,
)
from agent.config import settings
from agent.agent import app


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("agent.database.settings.config_db_path", path)
    yield path
    os.unlink(path)


@pytest.fixture
def _configure_oauth(monkeypatch):
    monkeypatch.setattr(settings, "github_oauth_client_id", "test-client-id")
    monkeypatch.setattr(settings, "github_oauth_client_secret", "test-client-secret")


@pytest.fixture
async def client():
    from agent.database import init_db
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestCreateAndDecodeSessionToken:
    def test_roundtrip(self):
        token = _create_session_token(user_id=1, github_id=1001, github_login="alice")
        payload = decode_session_token(token)
        assert payload["user_id"] == 1
        assert payload["github_id"] == 1001
        assert payload["github_login"] == "alice"

    def test_expired_token_raises(self):
        payload = {
            "user_id": 1, "github_id": 1001, "github_login": "alice",
            "exp": int(time.time()) - 10, "iat": int(time.time()) - 100,
        }
        token = jwt.encode(payload, settings.session_secret_key, algorithm=_JWT_ALGORITHM)
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_session_token(token)

    def test_invalid_signature_raises(self):
        token = jwt.encode(
            {"user_id": 1, "exp": int(time.time()) + 3600},
            "wrong-secret", algorithm=_JWT_ALGORITHM,
        )
        with pytest.raises(jwt.InvalidSignatureError):
            decode_session_token(token)


class TestGetCurrentUser:
    async def test_no_cookie_returns_401(self, client):
        resp = await client.get("/auth/me")
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client):
        resp = await client.get("/auth/me", cookies={"session": "garbage"})
        assert resp.status_code == 401

    async def test_expired_token_returns_401(self, client):
        payload = {
            "user_id": 1, "github_id": 1001, "github_login": "alice",
            "exp": int(time.time()) - 10, "iat": int(time.time()) - 100,
        }
        token = jwt.encode(payload, settings.session_secret_key, algorithm=_JWT_ALGORITHM)
        resp = await client.get("/auth/me", cookies={"session": token})
        assert resp.status_code == 401

    async def test_valid_token_missing_user_returns_401(self, client):
        token = _create_session_token(user_id=999, github_id=1001, github_login="ghost")
        resp = await client.get("/auth/me", cookies={"session": token})
        assert resp.status_code == 401

    async def test_valid_token_with_user_returns_profile(self, client):
        from agent.database import upsert_user
        user = await upsert_user(1001, "alice", "https://avatar/a", "tok")
        token = _create_session_token(
            user_id=user["id"], github_id=1001, github_login="alice"
        )
        resp = await client.get("/auth/me", cookies={"session": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["github_login"] == "alice"
        assert data["github_id"] == 1001


class TestGitHubLogin:
    async def test_redirects_to_github(self, client, _configure_oauth):
        resp = await client.get("/auth/github", follow_redirects=False)
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "github.com/login/oauth/authorize" in location
        assert "client_id=test-client-id" in location

    async def test_sets_state_cookie(self, client, _configure_oauth):
        resp = await client.get("/auth/github", follow_redirects=False)
        assert "oauth_state" in resp.cookies

    async def test_returns_503_when_not_configured(self, client, monkeypatch):
        monkeypatch.setattr(settings, "github_oauth_client_id", "")
        resp = await client.get("/auth/github")
        assert resp.status_code == 503


class TestGitHubCallback:
    async def test_invalid_state_returns_400(self, client, _configure_oauth):
        resp = await client.get(
            "/auth/callback?code=abc&state=wrong",
            cookies={"oauth_state": "expected"},
        )
        assert resp.status_code == 400

    async def test_missing_state_returns_400(self, client, _configure_oauth):
        resp = await client.get("/auth/callback?code=abc")
        assert resp.status_code == 400

    @patch("agent.auth.httpx.AsyncClient")
    async def test_successful_callback(self, mock_client_cls, client, _configure_oauth):
        state = "test-state-123"

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # First call: token exchange
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "gho_test123"}

        # Second call: user profile
        user_resp = MagicMock()
        user_resp.status_code = 200
        user_resp.json.return_value = {
            "id": 1001, "login": "alice", "avatar_url": "https://avatar/a"
        }

        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.get = AsyncMock(return_value=user_resp)

        resp = await client.get(
            f"/auth/callback?code=valid_code&state={state}",
            cookies={"oauth_state": state},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "session" in resp.cookies

    @patch("agent.auth.httpx.AsyncClient")
    async def test_token_exchange_failure(self, mock_client_cls, client, _configure_oauth):
        state = "test-state"

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        token_resp = MagicMock()
        token_resp.status_code = 500
        mock_client.post = AsyncMock(return_value=token_resp)

        resp = await client.get(
            f"/auth/callback?code=bad&state={state}",
            cookies={"oauth_state": state},
        )
        assert resp.status_code == 502

    @patch("agent.auth.httpx.AsyncClient")
    async def test_oauth_error_response(self, mock_client_cls, client, _configure_oauth):
        state = "test-state"

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"error": "bad_verification_code"}
        mock_client.post = AsyncMock(return_value=token_resp)

        resp = await client.get(
            f"/auth/callback?code=expired&state={state}",
            cookies={"oauth_state": state},
        )
        assert resp.status_code == 400


class TestLogout:
    async def test_clears_session_cookie(self, client):
        resp = await client.post("/auth/logout")
        assert resp.status_code == 200
