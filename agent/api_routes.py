"""REST API endpoints for review configuration CRUD."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from .auth import get_current_user
from .database import (
    delete_review_config,
    get_review_config,
    get_user_by_id,
    list_user_configs,
    upsert_review_config,
)
from .models import (
    OutputStyleConfig,
    PreviewRequest,
    ReviewConfigCreate,
)
from .prompts import REVIEW_TEMPLATE, build_review_prompt_with_config

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/api", tags=["config"])


@api_router.get("/config/defaults")
async def get_defaults(user: dict = Depends(get_current_user)):
    """Return the default prompt template and output style."""
    return {
        "prompt_template": REVIEW_TEMPLATE,
        "output_style": OutputStyleConfig().model_dump(),
    }


@api_router.get("/config")
async def list_configs(user: dict = Depends(get_current_user)):
    """List all review configs for the current user."""
    configs = await list_user_configs(user["id"])
    return configs


@api_router.get("/config/{repo_full_name:path}")
async def get_config(repo_full_name: str, user: dict = Depends(get_current_user)):
    """Get config for a specific repo, falling back to wildcard default."""
    config = await get_review_config(user["id"], repo_full_name)
    if not config:
        raise HTTPException(status_code=404, detail="No config found")
    return config


@api_router.put("/config/{repo_full_name:path}")
async def put_config(
    repo_full_name: str,
    body: ReviewConfigCreate,
    user: dict = Depends(get_current_user),
):
    """Create or update config for a repo."""
    config = await upsert_review_config(
        user_id=user["id"],
        repo_full_name=repo_full_name,
        prompt_template=body.prompt_template,
        output_style=body.output_style.model_dump(),
        severity_filter=body.severity_filter,
        active=body.active,
    )
    return config


@api_router.delete("/config/{repo_full_name:path}")
async def remove_config(repo_full_name: str, user: dict = Depends(get_current_user)):
    """Delete a repo-specific config."""
    deleted = await delete_review_config(user["id"], repo_full_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Config not found")
    return {"status": "deleted"}


@api_router.post("/config/preview")
async def preview_prompt(
    body: PreviewRequest,
    user: dict = Depends(get_current_user),
):
    """Render a prompt template with sample inputs for preview."""
    from .prompts import REQUIRED_PLACEHOLDERS, _validate_custom_template

    if body.prompt_template and not _validate_custom_template(body.prompt_template):
        missing = [p for p in REQUIRED_PLACEHOLDERS if p not in body.prompt_template]
        raise HTTPException(
            status_code=400,
            detail=f"Template missing required placeholders: {', '.join(sorted(missing))}",
        )

    try:
        rendered = build_review_prompt_with_config(
            body.filename,
            body.patch,
            pr_title=body.pr_title,
            pr_description=body.pr_description,
            custom_template=body.prompt_template,
        )
        return {"rendered_prompt": rendered}
    except (KeyError, IndexError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Template rendering failed: {e}",
        )


@api_router.get("/repos")
async def list_repos(user: dict = Depends(get_current_user)):
    """Fetch the authenticated user's GitHub repos using their OAuth token."""
    db_user = await get_user_by_id(user["id"])
    if not db_user or not db_user.get("access_token"):
        raise HTTPException(status_code=401, detail="No GitHub token available")

    repos = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            page = 1
            while True:
                resp = await client.get(
                    "https://api.github.com/user/repos",
                    headers={
                        "Authorization": f"Bearer {db_user['access_token']}",
                        "Accept": "application/vnd.github+json",
                    },
                    params={"per_page": 100, "page": page, "sort": "updated"},
                )
                if resp.status_code == 401:
                    raise HTTPException(
                        status_code=401,
                        detail="GitHub token expired or revoked, please re-authenticate",
                    )
                if resp.status_code != 200:
                    logger.warning(
                        "GitHub repos API returned %d on page %d", resp.status_code, page
                    )
                    raise HTTPException(status_code=502, detail="Failed to fetch repos from GitHub")
                page_data = resp.json()
                if not page_data:
                    break
                repos.extend(
                    {
                        "full_name": r["full_name"],
                        "name": r["name"],
                        "owner": r["owner"]["login"],
                        "private": r["private"],
                        "description": r.get("description") or "",
                        "language": r.get("language") or "",
                    }
                    for r in page_data
                )
                if len(page_data) < 100:
                    break
                page += 1
    except httpx.HTTPError as e:
        logger.error("HTTP error fetching repos: %s", e)
        raise HTTPException(status_code=502, detail="Failed to connect to GitHub API")

    return repos
