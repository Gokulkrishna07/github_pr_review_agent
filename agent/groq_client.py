import json
import logging
import re
import time

from groq import AsyncGroq

from .metrics import groq_request_duration_seconds, groq_requests_total, llm_tokens_used_total

logger = logging.getLogger(__name__)

FULL_FILE_MAX_LINES = 500  # files larger than this get diff-only review

REVIEW_PROMPT = """\
You are a senior code reviewer. Analyze the following changes and return a JSON object with categorized review feedback.

Return this exact structure:
{{
  "whats_good": ["<genuine positive observation>", ...],
  "critical": [{{"issue": "<description>", "location": "line <N>"}}],
  "major":    [{{"issue": "<description>", "location": "line <N>"}}],
  "minor":    [{{"issue": "<description>", "location": "line <N>"}}],
  "nit":      [{{"issue": "<description>", "location": "line <N>"}}]
}}

Severity guide:
- critical : bugs, security vulnerabilities, data loss risks
- major    : significant performance issues, missing error handling, logic errors
- minor    : code quality, readability, unclear naming
- nit      : style suggestions, minor improvements (non-blocking)
- whats_good: at least 1-2 genuine positives — never leave this empty

Rules:
- "location" must reference the line number visible in the diff
- Only flag issues clearly present in the code shown — do not assume things are missing if they are not visible
- Use empty array [] for categories with nothing to report
- If there are NO issues at all, set all issue arrays to [] and include "This is a solid PR and good to merge" as the first item in whats_good
- Return ONLY valid JSON, no other text

PR context: {pr_title}
{pr_description}

File: {filename}
{file_content_section}
Changes made in this PR:
```diff
{patch}
```
"""


def _sanitize_input(text: str, max_len: int) -> str:
    """Truncate text to max_len and strip triple backticks to prevent prompt injection."""
    text = text[:max_len]
    text = text.replace("```", "")
    return text


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
) -> dict:
    """Send a diff to Groq for review, return categorized review dict."""
    pr_title = _sanitize_input(pr_title, 200)
    pr_description = _sanitize_input(pr_description, 2000)
    description_section = f"PR description: {pr_description}" if pr_description.strip() else ""
    file_content_section = _build_file_content_section(file_content)
    prompt = REVIEW_PROMPT.format(
        filename=filename,
        patch=patch,
        pr_title=pr_title,
        pr_description=description_section,
        file_content_section=file_content_section,
    )

    client = AsyncGroq(api_key=api_key, timeout=timeout)
    start = time.monotonic()
    try:
        chat_completion = await client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.2,
            max_tokens=1024,
        )
        groq_requests_total.labels(status="success").inc()
    except Exception:
        groq_requests_total.labels(status="error").inc()
        raise
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


def _build_file_content_section(file_content: str | None) -> str:
    """Return the full file content block for the prompt, or empty string if unavailable/too large."""
    if not file_content:
        return ""
    line_count = file_content.count("\n") + 1
    if line_count > FULL_FILE_MAX_LINES:
        return ""
    return f"Full file content for context:\n```\n{file_content}\n```\n"


def _parse_response(text: str) -> dict:
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


def _validate_review(data: dict) -> dict:
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


def _empty_review() -> dict:
    return {"whats_good": [], "critical": [], "major": [], "minor": [], "nit": []}
