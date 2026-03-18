import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

REVIEW_PROMPT = """\
You are a senior code reviewer. Analyze the following diff and return a JSON array of review comments.

Each element must be: {{"line": <int>, "severity": "critical"|"warning"|"suggestion", "comment": "<string>"}}

Rules:
- "line" must be a line number from the diff (lines starting with +, using the new file line number).
- Focus on bugs, security issues, performance problems, and readability.
- Do NOT comment on style preferences or minor formatting.
- If nothing noteworthy, return an empty array: []
- Return ONLY the JSON array, no other text.

File: {filename}
```diff
{patch}
```
"""


async def review_diff(
    filename: str,
    patch: str,
    *,
    base_url: str,
    model: str,
    timeout: int,
) -> list[dict]:
    """Send a diff to Ollama for review, return parsed comments."""
    prompt = REVIEW_PROMPT.format(filename=filename, patch=patch)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 1024,
                },
            },
        )
        resp.raise_for_status()

    text = resp.json().get("response", "")
    return _parse_response(text)


def _parse_response(text: str) -> list[dict]:
    """Multi-layer parser: direct JSON → markdown code block → regex fallback."""
    text = text.strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return _validate_comments(result)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, list):
                return _validate_comments(result)
        except json.JSONDecodeError:
            pass

    # Regex fallback: find anything that looks like a JSON array
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return _validate_comments(result)
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM response: %s", text[:200])
    return []


def _validate_comments(items: list) -> list[dict]:
    """Filter to only well-formed comment objects."""
    valid = []
    for item in items:
        if (
            isinstance(item, dict)
            and isinstance(item.get("line"), int)
            and isinstance(item.get("comment"), str)
            and item.get("severity") in ("critical", "warning", "suggestion")
        ):
            valid.append(item)
    return valid
