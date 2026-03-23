"""Backward-compatible shim — delegates to agent.llm dispatcher."""

from .llm.base import (  # noqa: F401
    ReviewItem,
    ReviewResponse,
    parse_response as _parse_response,
    empty_review as _empty_review,
    _extract_candidates,
    _validate_review,
)
from .llm.dispatcher import review_diff  # noqa: F401
