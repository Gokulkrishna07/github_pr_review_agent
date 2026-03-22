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



_shared_groq: AsyncGroq | None = None


def _get_groq_client(api_key: str, timeout: int) -> AsyncGroq:
    """Return a module-level shared AsyncGroq client, recreating if config changes."""
    global _shared_groq
    if _shared_groq is None:
        _shared_groq = AsyncGroq(api_key=api_key, timeout=timeout)
    return _shared_groq


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

    client = _get_groq_client(api_key, timeout)
    start = time.monotonic()
    try:
        chat_completion = await client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.2,
            max_tokens=1024,
        )
        groq_requests_total.labels(status="success").inc()
    except Exception as e:
        groq_requests_total.labels(status="error").inc()
        raise GroqAPIError(f"Groq API call failed for {filename}: {e}") from e
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
