import asyncio
import logging

from fastapi import BackgroundTasks, FastAPI, Header, Request, Response

from .config import settings
from .diff_parser import parse_pr_files
from .github_client import get_pr_files, post_review
from .groq_client import review_diff
from .webhook_verify import verify_signature

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="PR Review Agent")


@app.get("/health")
async def health():
    return {"status": "ok"}



@app.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
):
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256, settings.gh_webhook_secret):
        return Response(status_code=401, content="Invalid signature")

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"event={x_github_event}"}

    payload = await request.json()
    action = payload.get("action", "")
    if action not in ("opened", "synchronize"):
        return {"status": "ignored", "reason": f"action={action}"}

    pr = payload["pull_request"]
    repo = payload["repository"]
    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]
    commit_sha = pr["head"]["sha"]

    logger.info("Processing PR #%d (%s/%s) action=%s", pr_number, owner, repo_name, action)
    background_tasks.add_task(
        process_review, owner, repo_name, pr_number, commit_sha
    )
    return {"status": "processing", "pr": pr_number}


async def process_review(
    owner: str, repo: str, pr_number: int, commit_sha: str
) -> None:
    """Background task: fetch diff, review with LLM, post comments."""
    try:
        files = await get_pr_files(owner, repo, pr_number, settings.gh_token)
        diffs = parse_pr_files(files, settings.max_diff_lines)

        if not diffs:
            logger.info("PR #%d: no reviewable files", pr_number)
            return

        logger.info("PR #%d: reviewing %d files", pr_number, len(diffs))

        semaphore = asyncio.Semaphore(3)

        async def review_one(diff):
            async with semaphore:
                return diff.filename, await review_diff(
                    diff.filename,
                    diff.patch,
                    api_key=settings.groq_api_key,
                    model=settings.groq_model,
                    timeout=settings.groq_timeout,
                )

        results = await asyncio.gather(
            *(review_one(d) for d in diffs), return_exceptions=True
        )

        # Build inline comments for GitHub review API
        review_comments = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Review failed: %s", result)
                continue
            filename, comments = result
            for c in comments:
                severity_prefix = {
                    "critical": "🔴",
                    "warning": "🟡",
                    "suggestion": "🔵",
                }.get(c["severity"], "")
                review_comments.append({
                    "path": filename,
                    "line": c["line"],
                    "body": f"{severity_prefix} **{c['severity'].upper()}**: {c['comment']}",
                })

        await post_review(
            owner, repo, pr_number, commit_sha, review_comments, settings.gh_token
        )
        logger.info("PR #%d: review complete, %d comments", pr_number, len(review_comments))

    except Exception:
        logger.exception("Failed to process review for PR #%d", pr_number)
