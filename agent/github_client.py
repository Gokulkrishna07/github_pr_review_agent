import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

BASE = "https://api.github.com"
MAX_RETRIES = 3


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def get_pr_files(
    owner: str, repo: str, pr_number: int, token: str
) -> list[dict]:
    """Fetch all files changed in a PR."""
    url = f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await _request_with_retry(client, "GET", url, token=token)
        resp.raise_for_status()
        return resp.json()


async def post_review(
    owner: str,
    repo: str,
    pr_number: int,
    commit_sha: str,
    comments: list[dict],
    token: str,
) -> None:
    """Post a review with inline comments to a PR."""
    if not comments:
        logger.info("No comments to post for PR #%d", pr_number)
        return

    url = f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    body = {
        "commit_id": commit_sha,
        "event": "COMMENT",
        "comments": comments,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await _request_with_retry(
            client, "POST", url, token=token, json=body
        )
        resp.raise_for_status()
    logger.info("Posted review with %d comments on PR #%d", len(comments), pr_number)


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    token: str,
    json: dict | None = None,
) -> httpx.Response:
    """Retry on 403/429 with exponential backoff."""
    for attempt in range(MAX_RETRIES):
        resp = await client.request(
            method, url, headers=_headers(token), json=json
        )
        if resp.status_code in (403, 429) and attempt < MAX_RETRIES - 1:
            wait = 2 ** (attempt + 1)
            logger.warning(
                "Rate limited (%d), retrying in %ds...", resp.status_code, wait
            )
            await asyncio.sleep(wait)
            continue
        return resp
    return resp
