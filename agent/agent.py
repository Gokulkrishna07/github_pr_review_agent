import asyncio
import json
import logging
import time

from fastapi import BackgroundTasks, FastAPI, Header, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import settings
from .diff_parser import parse_pr_files
from .github_client import get_pr_details, get_pr_files, post_pr_comment
from .groq_client import review_diff
from .idempotency import is_already_reviewed, mark_as_reviewed
from .metrics import active_reviews, pr_review_duration_seconds, pr_reviews_total
from .webhook_verify import verify_signature


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log: dict = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log)


_handler = logging.StreamHandler()
_handler.setFormatter(_JSONFormatter())
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    handlers=[_handler],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="PR Review Agent")

_semaphore = asyncio.Semaphore(3)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


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

    logger.info(
        "Processing PR #%d (%s/%s) action=%s", pr_number, owner, repo_name, action
    )
    background_tasks.add_task(process_review, owner, repo_name, pr_number, commit_sha)
    return {"status": "processing", "pr": pr_number}


async def process_review(
    owner: str, repo: str, pr_number: int, commit_sha: str
) -> None:
    """Background task: fetch diff, review with LLM, post single summary comment."""
    if is_already_reviewed(owner, repo, pr_number, commit_sha):
        logger.info("PR #%d (%s) already reviewed, skipping", pr_number, commit_sha[:7])
        pr_reviews_total.labels(status="duplicate").inc()
        return

    active_reviews.inc()
    start = time.monotonic()

    try:
        pr_details = await get_pr_details(owner, repo, pr_number, settings.gh_token)
        files = await get_pr_files(owner, repo, pr_number, settings.gh_token)
        diffs = parse_pr_files(files, settings.max_diff_lines)

        if not diffs:
            logger.info("PR #%d: no reviewable files", pr_number)
            pr_reviews_total.labels(status="skipped").inc()
            return

        logger.info("PR #%d: reviewing %d files", pr_number, len(diffs))

        async def review_one(diff):
            async with _semaphore:
                return diff.filename, await review_diff(
                    diff.filename,
                    diff.patch,
                    pr_title=pr_details["title"],
                    pr_description=pr_details["description"],
                    api_key=settings.groq_api_key,
                    model=settings.groq_model,
                    timeout=settings.groq_timeout,
                )

        results = await asyncio.gather(*(review_one(d) for d in diffs), return_exceptions=True)

        file_reviews = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Review failed for a file: %s", result)
            else:
                file_reviews.append(result)

        if not file_reviews:
            pr_reviews_total.labels(status="failed").inc()
            return

        body = _build_review_body(file_reviews, pr_details["title"], settings.groq_model)
        await post_pr_comment(owner, repo, pr_number, body, settings.gh_token)

        mark_as_reviewed(owner, repo, pr_number, commit_sha)
        pr_reviews_total.labels(status="success").inc()
        logger.info("PR #%d: review complete", pr_number)

    except Exception:
        pr_reviews_total.labels(status="failed").inc()
        logger.exception("Failed to process review for PR #%d", pr_number)
    finally:
        active_reviews.dec()
        pr_review_duration_seconds.observe(time.monotonic() - start)


def _build_review_body(
    file_reviews: list[tuple[str, dict]], pr_title: str, model: str
) -> str:
    all_good: list[str] = []
    all_critical: list[str] = []
    all_major: list[str] = []
    all_minor: list[str] = []
    all_nit: list[str] = []

    for filename, review in file_reviews:
        all_good.extend(review.get("whats_good", []))
        for item in review.get("critical", []):
            all_critical.append(f"{item['issue']} `[{filename} {item.get('location', '')}]`")
        for item in review.get("major", []):
            all_major.append(f"{item['issue']} `[{filename} {item.get('location', '')}]`")
        for item in review.get("minor", []):
            all_minor.append(f"{item['issue']} `[{filename} {item.get('location', '')}]`")
        for item in review.get("nit", []):
            all_nit.append(f"{item['issue']} `[{filename} {item.get('location', '')}]`")

    lines = ["## Code Review 🤖", "", "---"]

    if all_good:
        lines += ["", "### ✅ What's Good"]
        lines += [f"- {g}" for g in all_good]

    has_issues = any([all_critical, all_major, all_minor, all_nit])

    if has_issues:
        lines += ["", "### Issues Found", ""]

        if all_critical:
            lines += ["**🔴 Critical:**"]
            for i, issue in enumerate(all_critical, 1):
                lines.append(f"- issue {i} — {issue}")
            lines.append("")

        if all_major:
            lines += ["**🟡 Major:**"]
            for i, issue in enumerate(all_major, 1):
                lines.append(f"- issue {i} — {issue}")
            lines.append("")

        if all_minor:
            lines += ["**🔵 Minor:**"]
            for i, issue in enumerate(all_minor, 1):
                lines.append(f"- issue {i} — {issue}")
            lines.append("")

        if all_nit:
            lines += ["**💡 Nit:** *(non-blocking)*"]
            for i, issue in enumerate(all_nit, 1):
                lines.append(f"- issue {i} — {issue}")
            lines.append("")
    else:
        lines += ["", "### ✅ No issues found — looks good!"]

    lines += ["", "---", f"*Reviewed by PR Review Bot · powered by Groq {model}*"]
    return "\n".join(lines)
