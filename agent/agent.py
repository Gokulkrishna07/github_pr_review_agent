import asyncio
import contextvars
import json
import logging
import time
import uuid

from fastapi import BackgroundTasks, FastAPI, Header, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import settings
from .diff_parser import parse_pr_files
from .exceptions import AgentError, GroqAPIError
from .github_app import get_installation_token
from .github_client import get_file_content, get_pr_details, get_pr_files, post_pr_comment
from .groq_client import review_diff
from .idempotency import is_already_reviewed, mark_as_reviewed
from .types import FileReview
from .metrics import active_reviews, pr_review_duration_seconds, pr_reviews_total, review_queue_depth
from .webhook_verify import verify_signature

trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log: dict = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": trace_id.get(),
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

_MAX_CONCURRENT_REVIEWS = 3
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REVIEWS)

_ip_request_times: dict[str, list[float]] = {}
_RATE_LIMIT_MAX_REQUESTS = 60
_RATE_LIMIT_WINDOW_SECONDS = 60


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """Readiness probe: returns 503 if all review slots are occupied."""
    if active_reviews._value.get() >= _MAX_CONCURRENT_REVIEWS:
        return Response(status_code=503, content="At capacity")
    return {"status": "ready"}


@app.get("/metrics")
async def metrics(request: Request):
    client_ip = request.client.host if request.client else ""
    if not (client_ip in ("127.0.0.1", "::1") or client_ip.startswith(("10.", "172.", "192.168."))):
        return Response(status_code=403, content="Forbidden")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
):
    delivery_id = x_github_delivery or str(uuid.uuid4())
    trace_id.set(delivery_id)

    body = await request.body()

    if len(body) > 25 * 1024 * 1024:
        return Response(status_code=413, content="Payload too large")

    if not verify_signature(body, x_hub_signature_256, settings.gh_webhook_secret):
        client_ip = request.client.host if request.client else "unknown"
        logger.warning("Invalid signature from %s", client_ip)
        return Response(status_code=401, content="Invalid signature")

    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS
    times = _ip_request_times.get(client_ip, [])
    times = [t for t in times if t > window_start]
    if len(times) >= _RATE_LIMIT_MAX_REQUESTS:
        return Response(status_code=429, content="Too many requests")
    times.append(now)
    _ip_request_times[client_ip] = times

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"event={x_github_event}"}

    try:
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
        installation_id = payload["installation"]["id"]
    except (KeyError, Exception):
        return Response(status_code=400, content="Malformed payload")

    logger.info(
        "Processing PR #%d (%s/%s) action=%s", pr_number, owner, repo_name, action
    )
    review_queue_depth.inc()
    background_tasks.add_task(
        process_review, owner, repo_name, pr_number, commit_sha, installation_id, delivery_id
    )
    return {"status": "processing", "pr": pr_number}


async def process_review(
    owner: str, repo: str, pr_number: int, commit_sha: str,
    installation_id: int, delivery_id: str = "-",
) -> None:
    """Background task: fetch diff, review with LLM, post single summary comment."""
    trace_id.set(delivery_id)
    review_queue_depth.dec()

    if await is_already_reviewed(owner, repo, pr_number, commit_sha):
        logger.info("PR #%d (%s) already reviewed, skipping", pr_number, commit_sha[:7])
        pr_reviews_total.labels(status="duplicate").inc()
        return

    active_reviews.inc()
    start = time.monotonic()

    try:
        token = await get_installation_token(
            settings.github_app_id, settings.github_app_private_key, installation_id
        )

        pr_details = await get_pr_details(owner, repo, pr_number, token)
        files = await get_pr_files(owner, repo, pr_number, token)
        diffs = parse_pr_files(files, settings.max_diff_lines)

        if not diffs:
            logger.info("PR #%d: no reviewable files", pr_number)
            pr_reviews_total.labels(status="skipped").inc()
            return

        logger.info("PR #%d: reviewing %d files", pr_number, len(diffs))

        _per_file_timeout = settings.groq_timeout * 2  # generous per-file budget

        async def review_one(diff):
            async with _semaphore:
                file_content = await get_file_content(
                    owner, repo, diff.filename, commit_sha, token
                )
                return diff.filename, await review_diff(
                    diff.filename,
                    diff.patch,
                    pr_title=pr_details["title"],
                    pr_description=pr_details["description"],
                    api_key=settings.groq_api_key,
                    model=settings.groq_model,
                    timeout=settings.groq_timeout,
                    file_content=file_content,
                )

        results = await asyncio.gather(
            *(asyncio.wait_for(review_one(d), timeout=_per_file_timeout) for d in diffs),
            return_exceptions=True,
        )

        file_reviews = []
        for i, result in enumerate(results):
            if isinstance(result, asyncio.TimeoutError):
                logger.error("File review timed out after %ds: %s", _per_file_timeout, diffs[i].filename)
            elif isinstance(result, GroqAPIError):
                logger.error("LLM review failed for a file: %s", result)
            elif isinstance(result, AgentError):
                logger.error("Agent error during file review: %s", result)
            elif isinstance(result, Exception):
                logger.error("Unexpected error during file review: %s", result)
            else:
                file_reviews.append(result)

        if not file_reviews:
            pr_reviews_total.labels(status="failed").inc()
            return

        body = _build_review_body(file_reviews, pr_details["title"], settings.groq_model)
        await post_pr_comment(owner, repo, pr_number, body, token)

        await mark_as_reviewed(owner, repo, pr_number, commit_sha)
        pr_reviews_total.labels(status="success").inc()
        logger.info("PR #%d: review complete", pr_number)

    except Exception:
        pr_reviews_total.labels(status="failed").inc()
        logger.exception("Failed to process review for PR #%d", pr_number)
    finally:
        active_reviews.dec()
        pr_review_duration_seconds.observe(time.monotonic() - start)


def _build_review_body(
    file_reviews: list[tuple[str, FileReview]], pr_title: str, model: str
) -> str:
    all_good: list[str] = []
    all_critical: list[str] = []
    all_major: list[str] = []
    all_minor: list[str] = []
    all_nit: list[str] = []

    for filename, review in file_reviews:
        for item in review.get("whats_good", []):
            if item not in all_good:
                all_good.append(item)
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
        lines += ["", "### ✅ This is a solid PR and good to merge"]

    lines += ["", "---", f"*Reviewed by PR Review Bot · powered by Groq {model}*"]
    return "\n".join(lines)
