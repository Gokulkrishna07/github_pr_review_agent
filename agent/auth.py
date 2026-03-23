"""GitHub OAuth authentication and JWT session management."""

from __future__ import annotations

import hashlib
import logging
import os
import time

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from .config import settings
from .database import get_user_by_id, upsert_user

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["auth"])

_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_SECONDS = 7 * 24 * 3600  # 7 days
_OAUTH_SCOPES = "read:user repo"


def _check_oauth_configured() -> None:
    if not settings.github_oauth_client_id or not settings.github_oauth_client_secret:
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")


def _create_session_token(user_id: int, github_id: int, github_login: str) -> str:
    payload = {
        "user_id": user_id,
        "github_id": github_id,
        "github_login": github_login,
        "exp": int(time.time()) + _JWT_EXPIRY_SECONDS,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, settings.session_secret_key, algorithm=_JWT_ALGORITHM)


def decode_session_token(token: str) -> dict:
    """Decode and validate a JWT session token. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, settings.session_secret_key, algorithms=[_JWT_ALGORITHM])


async def get_current_user(request: Request) -> dict:
    """FastAPI dependency: extract authenticated user from session cookie."""
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_session_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = await get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@auth_router.get("/github")
async def github_login(request: Request):
    """Redirect to GitHub OAuth authorization page."""
    _check_oauth_configured()
    state = hashlib.sha256(os.urandom(32)).hexdigest()
    params = {
        "client_id": settings.github_oauth_client_id,
        "scope": _OAUTH_SCOPES,
        "state": state,
    }
    redirect_uri = settings.frontend_url
    if redirect_uri:
        params["redirect_uri"] = f"{redirect_uri}/auth/callback"

    url = f"{_GITHUB_AUTHORIZE_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    response = RedirectResponse(url=url)
    response.set_cookie(
        "oauth_state", state, httponly=True, max_age=600, samesite="lax"
    )
    return response


@auth_router.get("/callback")
async def github_callback(request: Request, code: str = "", state: str = ""):
    """Handle GitHub OAuth callback: exchange code for token, create session."""
    _check_oauth_configured()

    stored_state = request.cookies.get("oauth_state", "")
    if not state or not stored_state or state != stored_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # Exchange code for access token
    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(
            _GITHUB_TOKEN_URL,
            json={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to exchange OAuth code")
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        error = token_data.get("error_description", token_data.get("error", "unknown"))
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")

    # Fetch user profile
    async with httpx.AsyncClient(timeout=30) as client:
        user_resp = await client.get(
            _GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch GitHub user")
        user_data = user_resp.json()

    github_id = user_data["id"]
    github_login = user_data["login"]
    avatar_url = user_data.get("avatar_url", "")

    user = await upsert_user(github_id, github_login, avatar_url, access_token)

    session_token = _create_session_token(user["id"], github_id, github_login)

    redirect_url = settings.frontend_url or "/"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        "session", session_token,
        httponly=True, max_age=_JWT_EXPIRY_SECONDS, samesite="lax",
    )
    response.delete_cookie("oauth_state")
    return response


@auth_router.get("/me")
async def get_me(request: Request):
    """Return the currently authenticated user."""
    user = await get_current_user(request)
    return {
        "github_id": user["github_id"],
        "github_login": user["github_login"],
        "avatar_url": user["avatar_url"],
    }


@auth_router.post("/logout")
async def logout():
    """Clear the session cookie."""
    response = Response(status_code=200)
    response.delete_cookie("session")
    return response
