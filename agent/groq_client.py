import asyncio
import json
import logging
import re
import time

from groq import AsyncGroq
from pydantic import BaseModel, ValidationError

from .exceptions import GroqAPIError
from .metrics import groq_request_duration_seconds, groq_requests_total, llm_tokens_used_total
from .prompts import build_review_prompt
from .types import FileReview

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}



class ReviewItem(BaseModel):
    """A single review issue with location."""
    issue: str
    location: str = ""


class ReviewResponse(BaseModel):
    """Schema for validated LLM review response."""
    whats_good: list[str] = []
    critical: list[ReviewItem] = []
    major: list[ReviewItem] = []
    minor: list[ReviewItem] = []
    nit: list[ReviewItem] = []



async def review_diff(
    filename: str,
    patch: str,
    *,
    pr_title: str,
    pr_description: str,
    api_key: str,
    model: str,
    timeout: int,
    file_content: str | None = None,
) -> FileReview:
    """Send a diff to Groq for review, return categorized review dict."""
    prompt = build_review_prompt(
        filename, patch,
        pr_title=pr_title,
        pr_description=pr_description,
        file_content=file_content,
    )

    client = AsyncGroq(api_key=api_key, timeout=timeout)
    start = time.monotonic()
    last_error: Exception | None = None
    try:
        for attempt in range(MAX_RETRIES):
            try:
                chat_completion = await client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=model,
                    temperature=0.2,
                    max_tokens=1024,
                )
                groq_requests_total.labels(status="success").inc()
                break
            except Exception as e:
                last_error = e
                status_code = getattr(e, "status_code", None)
                if status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "Groq API error for %s (status %s), retrying in %ds (attempt %d/%d)...",
                        filename, status_code, wait, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    continue
                groq_requests_total.labels(status="error").inc()
                raise GroqAPIError(f"Groq API call failed for {filename}: {e}") from e
        else:
            groq_requests_total.labels(status="error").inc()
            raise GroqAPIError(f"Groq API call failed for {filename} after {MAX_RETRIES} retries: {last_error}") from last_error
    finally:
        groq_request_duration_seconds.observe(time.monotonic() - start)

    usage = getattr(chat_completion, "usage", None)
    if usage:
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        if prompt_tokens:
            llm_tokens_used_total.labels(type="prompt").inc(prompt_tokens)
        if completion_tokens:
            llm_tokens_used_total.labels(type="completion").inc(completion_tokens)

    text = chat_completion.choices[0].message.content or ""
    return _parse_response(text)


def _parse_response(text: str) -> FileReview:
    """Multi-layer parser: direct JSON → markdown block → regex fallback."""
    text = text.strip()

    for candidate in _extract_candidates(text):
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return _validate_review(result)
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM response: %s", text[:200])
    return _empty_review()


def _extract_candidates(text: str) -> list[str]:
    candidates = [text]

    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        candidates.append(m.group(1).strip())

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        candidates.append(m.group(0))

    return candidates


def _validate_review(data: dict) -> FileReview:
    """Validate LLM response against ReviewResponse schema, filtering invalid items."""
    try:
        validated = ReviewResponse(**data)
        return validated.model_dump()
    except ValidationError:
        logger.warning("LLM response failed schema validation, falling back to manual filter: %s", str(data)[:200])
        # Graceful fallback: manually extract what we can
        result = _empty_review()
        for key in ("whats_good",):
            result[key] = [str(i) for i in data.get(key, []) if isinstance(i, str)]
        for key in ("critical", "major", "minor", "nit"):
            for item in data.get(key, []):
                if isinstance(item, dict) and isinstance(item.get("issue"), str):
                    result[key].append(
                        {"issue": item["issue"], "location": str(item.get("location", ""))}
                    )
        return result


def _empty_review() -> FileReview:
    return ReviewResponse().model_dump()
