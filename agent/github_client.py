import asyncio
import base64
import logging
import time

import httpx

from .metrics import github_request_duration_seconds, retry_attempts_total

logger = logging.getLogger(__name__)

BASE = "https://api.github.com"
MAX_RETRIES = 3
PAGE_SIZE = 100
RETRYABLE_STATUS_CODES = {403, 429, 500, 502, 503, 504}


class GitHubAPIError(RuntimeError):
    """Raised when the GitHub API returns a non-JSON or unexpected response."""


def _parse_json(resp: httpx.Response):
    """Parse JSON from a response, raising a clear error on non-JSON bodies."""
    try:
        return resp.json()
    except ValueError as e:
        raise GitHubAPIError(
            f"GitHub API returned non-JSON (status {resp.status_code}): "
            f"{resp.text[:200]}"
        ) from e


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
        resp = await _request_with_retry(client, "GET", url, token=token, endpoint="pr_details")
        resp.raise_for_status()
        data = _parse_json(resp)
        return {
            "title": data.get("title", ""),
            "description": data.get("body", "") or "",
        }


async def get_pr_files(
    owner: str, repo: str, pr_number: int, token: str
) -> list[dict]:
    """Fetch all files changed in a PR with parallel pagination."""
    url = f"{BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"

    async def _fetch_page(client: httpx.AsyncClient, page: int) -> list[dict]:
        r = await _request_with_retry(
            client, "GET", url, token=token,
            params={"per_page": PAGE_SIZE, "page": page},
            endpoint="pr_files",
        )
        r.raise_for_status()
        return _parse_json(r)

    async with httpx.AsyncClient(timeout=30) as client:
        first_page = await _fetch_page(client, 1)

        if len(first_page) < PAGE_SIZE:
            return first_page

        # First page full — speculatively fetch pages 2-4 in parallel
        extra = await asyncio.gather(*[_fetch_page(client, p) for p in range(2, 5)])

        files = list(first_page)
        for page_data in extra:
            files.extend(page_data)
            if len(page_data) < PAGE_SIZE:
                return files

        # Still more pages — continue sequentially from page 5
        page = 5
        while True:
            page_data = await _fetch_page(client, page)
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
            client, "GET", url, token=token, params={"ref": commit_sha},
            endpoint="file_content",
        )
        if resp.status_code != 200:
            logger.warning("Could not fetch content for %s (status %d)", path, resp.status_code)
            return None
        data = _parse_json(resp)
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
            client, "POST", url, token=token, json={"body": body},
            endpoint="post_comment",
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
    endpoint: str = "unknown",
) -> httpx.Response:
    """Retry on rate-limit and transient server errors with exponential backoff."""
    start = time.monotonic()
    try:
        for attempt in range(MAX_RETRIES):
            resp = await client.request(
                method, url, headers=_headers(token), json=json, params=params
            )
            if resp.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES - 1:
                retry_attempts_total.inc()
                wait = 2 ** (attempt + 1)
                logger.warning("GitHub API error (%d), retrying in %ds...", resp.status_code, wait)
                await asyncio.sleep(wait)
                continue
            return resp
        return resp
    finally:
        github_request_duration_seconds.labels(endpoint=endpoint).observe(
            time.monotonic() - start
        )
