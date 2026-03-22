"""GitHub App authentication: JWT signing and installation token management."""

import logging
import time

import httpx
import jwt

logger = logging.getLogger(__name__)

BASE = "https://api.github.com"

# Tokens are cached and refreshed 5 minutes before expiry
_TOKEN_BUFFER_SECONDS = 300
_token_cache: dict[int, tuple[str, float]] = {}  # installation_id -> (token, expiry_timestamp)


def generate_jwt(app_id: str, private_key: str) -> str:
    """Generate a JWT signed with the GitHub App's private key. Valid for 10 minutes."""
    now = int(time.time())
    payload = {
        "iat": now - 60,  # issued at (60s in past to handle clock drift)
        "exp": now + (10 * 60),  # expires in 10 minutes
        "iss": app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_token(app_id: str, private_key: str, installation_id: int) -> str:
    """Get an installation access token, using cache when possible."""
    cached = _token_cache.get(installation_id)
    if cached:
        token, expiry = cached
        if time.time() < expiry - _TOKEN_BUFFER_SECONDS:
            return token

    jwt_token = generate_jwt(app_id, private_key)
    url = f"{BASE}/app/installations/{installation_id}/access_tokens"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    token = data["token"]
    # GitHub installation tokens expire in 1 hour
    expiry = time.time() + 3600
    _token_cache[installation_id] = (token, expiry)
    logger.info("Obtained new installation token for installation %d", installation_id)
    return token


def clear_token_cache() -> None:
    """Clear the token cache (useful for testing)."""
    _token_cache.clear()
