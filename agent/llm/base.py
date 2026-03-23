"""Shared response parsing logic extracted from groq_client.py."""

import json
import logging
import re

from pydantic import BaseModel, ValidationError

from ..types import FileReview

logger = logging.getLogger(__name__)


class ReviewItem(BaseModel):
    issue: str
    location: str = ""


class ReviewResponse(BaseModel):
    whats_good: list[str] = []
    critical: list[ReviewItem] = []
    major: list[ReviewItem] = []
    minor: list[ReviewItem] = []
    nit: list[ReviewItem] = []


def parse_response(text: str) -> FileReview:
    """Multi-layer parser: direct JSON -> markdown block -> regex fallback."""
    text = text.strip()
    for candidate in _extract_candidates(text):
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return _validate_review(result)
        except json.JSONDecodeError:
            pass
    logger.warning("Failed to parse LLM response: %s", text[:200])
    return empty_review()


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
    try:
        validated = ReviewResponse(**data)
        return validated.model_dump()
    except ValidationError:
        logger.warning("LLM response failed schema validation, falling back to manual filter")
        result = empty_review()
        for key in ("whats_good",):
            result[key] = [str(i) for i in data.get(key, []) if isinstance(i, str)]
        for key in ("critical", "major", "minor", "nit"):
            for item in data.get(key, []):
                if isinstance(item, dict) and isinstance(item.get("issue"), str):
                    result[key].append(
                        {"issue": item["issue"], "location": str(item.get("location", ""))}
                    )
        return result


def empty_review() -> FileReview:
    return ReviewResponse().model_dump()
