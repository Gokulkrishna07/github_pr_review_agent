"""Tests for agent.github_app — JWT signing and installation token management."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.github_app import (
    _token_cache,
    clear_token_cache,
    generate_jwt,
    get_installation_token,
)


# Use a real RSA key for JWT tests (2048-bit, test-only)
import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

_test_private_key_obj = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_TEST_PRIVATE_KEY = _test_private_key_obj.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_TEST_PUBLIC_KEY = _test_private_key_obj.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()


class TestGenerateJWT:
    def test_returns_valid_jwt(self):
        token = generate_jwt("123", _TEST_PRIVATE_KEY)
        assert isinstance(token, str)
        assert len(token) > 50

    def test_jwt_has_correct_issuer(self):
        token = generate_jwt("myapp123", _TEST_PRIVATE_KEY)
        decoded = pyjwt.decode(token, _TEST_PUBLIC_KEY, algorithms=["RS256"])
        assert decoded["iss"] == "myapp123"

    def test_jwt_has_iat_and_exp(self):
        token = generate_jwt("123", _TEST_PRIVATE_KEY)
        decoded = pyjwt.decode(token, _TEST_PUBLIC_KEY, algorithms=["RS256"])
        assert "iat" in decoded
        assert "exp" in decoded
        assert decoded["exp"] > decoded["iat"]

    def test_jwt_expires_in_10_minutes(self):
        token = generate_jwt("123", _TEST_PRIVATE_KEY)
        decoded = pyjwt.decode(token, _TEST_PUBLIC_KEY, algorithms=["RS256"])
        # exp - iat should be ~11 minutes (10 min + 60s clock drift buffer)
        diff = decoded["exp"] - decoded["iat"]
        assert 600 <= diff <= 720


class TestGetInstallationToken:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_token_cache()
        yield
        clear_token_cache()

    async def test_fetches_token_from_github(self):
        fake_resp = MagicMock()
        fake_resp.status_code = 201
        fake_resp.json.return_value = {"token": "ghs_installation_token_123"}
        fake_resp.raise_for_status = MagicMock()

        with patch("agent.github_app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=fake_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            token = await get_installation_token("123", _TEST_PRIVATE_KEY, 456)

        assert token == "ghs_installation_token_123"

    async def test_returns_cached_token(self):
        # Pre-populate cache with a token that expires far in the future
        _token_cache[789] = ("cached_token", time.time() + 3600)

        token = await get_installation_token("123", _TEST_PRIVATE_KEY, 789)
        assert token == "cached_token"

    async def test_refreshes_expired_token(self):
        # Pre-populate cache with an expired token
        _token_cache[101] = ("old_token", time.time() - 100)

        fake_resp = MagicMock()
        fake_resp.json.return_value = {"token": "new_token_abc"}
        fake_resp.raise_for_status = MagicMock()

        with patch("agent.github_app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=fake_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            token = await get_installation_token("123", _TEST_PRIVATE_KEY, 101)

        assert token == "new_token_abc"

    async def test_refreshes_token_near_expiry(self):
        # Token expires in 4 minutes (within 5-minute buffer)
        _token_cache[202] = ("expiring_token", time.time() + 240)

        fake_resp = MagicMock()
        fake_resp.json.return_value = {"token": "fresh_token"}
        fake_resp.raise_for_status = MagicMock()

        with patch("agent.github_app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=fake_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            token = await get_installation_token("123", _TEST_PRIVATE_KEY, 202)

        assert token == "fresh_token"


class TestClearTokenCache:
    def test_clears_cache(self):
        _token_cache[1] = ("token", time.time() + 3600)
        _token_cache[2] = ("token2", time.time() + 3600)
        clear_token_cache()
        assert len(_token_cache) == 0
