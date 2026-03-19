import asyncio
import base64
import logging

import httpx

logger = logging.getLogger(__name__)

BASE = "https://api.github.com"
MAX_RETRIES = 3
PAGE_SIZE = 100


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def get_pr_details(owner: str, repo: str, pr_number: int, token: str) -> dict:
    """Fetch PR title and description."""
    url = f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await _request_with_retry(client, "GET", url, token=token)
        resp.raise_for_status()
        data = resp.json()
        return {
            "title": data.get("title", ""),
            "description": data.get("body", "") or "",
        }


async def get_pr_files(
    owner: str, repo: str, pr_number: int, token: str
) -> list[dict]:
    """Fetch all files changed in a PR (handles pagination)."""
    files = []
    page = 1
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            url = f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"
            resp = await _request_with_retry(
                client, "GET", url, token=token,
                params={"per_page": PAGE_SIZE, "page": page},
            )
            resp.raise_for_status()
            page_data = resp.json()
            files.extend(page_data)
            if len(page_data) < PAGE_SIZE:
                break
            page += 1
    return files


async def get_file_content(
    owner: str, repo: str, path: str, commit_sha: str, token: str
) -> str | None:
    """Fetch full file content at a specific commit. Returns None if unavailable."""
    url = f"{BASE}/repos/{owner}/{repo}/contents/{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await _request_with_retry(
            client, "GET", url, token=token, params={"ref": commit_sha}
        )
        if resp.status_code != 200:
            logger.warning("Could not fetch content for %s (status %d)", path, resp.status_code)
            return None
        data = resp.json()
        if data.get("encoding") != "base64" or not data.get("content"):
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")


async def post_pr_comment(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    token: str,
) -> None:
    """Post a single summary comment to the PR conversation."""
    url = f"{BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await _request_with_retry(
            client, "POST", url, token=token, json={"body": body}
        )
        resp.raise_for_status()
    logger.info("Posted review comment on PR #%d", pr_number)


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    token: str,
    json: dict | None = None,
    params: dict | None = None,
) -> httpx.Response:
    """Retry on 403/429 with exponential backoff."""
    for attempt in range(MAX_RETRIES):
        resp = await client.request(
            method, url, headers=_headers(token), json=json, params=params
        )
        if resp.status_code in (403, 429) and attempt < MAX_RETRIES - 1:
            wait = 2 ** (attempt + 1)
            logger.warning("Rate limited (%d), retrying in %ds...", resp.status_code, wait)
            await asyncio.sleep(wait)
            continue
        return resp
    return resp
