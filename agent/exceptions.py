"""Structured exception hierarchy for the PR review agent."""


class AgentError(Exception):
    """Base exception for all agent errors."""


class GitHubAPIError(AgentError):
    """Raised when the GitHub API returns an unexpected response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"GitHub API error ({status_code}): {message}")


class GitHubRateLimitError(GitHubAPIError):
    """Raised when GitHub returns 403/429 rate limit responses."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(status_code=429, message=message)


class GroqAPIError(AgentError):
    """Raised when the Groq LLM API call fails."""


class GroqParseError(AgentError):
    """Raised when the Groq LLM response cannot be parsed as valid JSON."""


class IdempotencyError(AgentError):
    """Raised when the idempotency store (SQLite) fails."""
