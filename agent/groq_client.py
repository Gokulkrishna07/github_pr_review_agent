import json
import logging
import re

from groq import AsyncGroq

from .metrics import groq_requests_total

logger = logging.getLogger(__name__)

REVIEW_PROMPT = """\
You are a senior code reviewer. Analyze the following diff and return a JSON object with categorized review feedback.

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
- Use empty array [] for categories with nothing to report
- Return ONLY valid JSON, no other text

PR context: {pr_title}
{pr_description}

File: {filename}
```diff
{patch}
```
"""


async def review_diff(
    filename: str,
    patch: str,
    *,
    pr_title: str,
    pr_description: str,
    api_key: str,
    model: str,
    timeout: int,
) -> dict:
    """Send a diff to Groq for review, return categorized review dict."""
    description_section = f"PR description: {pr_description}" if pr_description.strip() else ""
    prompt = REVIEW_PROMPT.format(
        filename=filename,
        patch=patch,
        pr_title=pr_title,
        pr_description=description_section,
    )

    client = AsyncGroq(api_key=api_key, timeout=timeout)
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

    text = chat_completion.choices[0].message.content or ""
    return _parse_response(text)


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
