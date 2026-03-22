from typing import TypedDict


class ReviewComment(TypedDict):
    """A single review issue with location info."""
    issue: str
    location: str


class FileReview(TypedDict):
    """Structured review result for a single file."""
    whats_good: list[str]
    critical: list[ReviewComment]
    major: list[ReviewComment]
    minor: list[ReviewComment]
    nit: list[ReviewComment]
