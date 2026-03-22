"""Tests for agent.exceptions — structured exception hierarchy."""

import pytest

from agent.exceptions import (
    AgentError,
    GitHubAPIError,
    GitHubRateLimitError,
    GroqAPIError,
    GroqParseError,
    IdempotencyError,
)


class TestExceptionHierarchy:
    def test_all_exceptions_inherit_from_agent_error(self):
        assert issubclass(GitHubAPIError, AgentError)
        assert issubclass(GitHubRateLimitError, AgentError)
        assert issubclass(GroqAPIError, AgentError)
        assert issubclass(GroqParseError, AgentError)
        assert issubclass(IdempotencyError, AgentError)

    def test_agent_error_inherits_from_exception(self):
        assert issubclass(AgentError, Exception)

    def test_github_rate_limit_inherits_from_github_api_error(self):
        assert issubclass(GitHubRateLimitError, GitHubAPIError)

    def test_catch_agent_error_catches_all_subtypes(self):
        exceptions = [
            GitHubAPIError(502, "Bad Gateway"),
            GitHubRateLimitError(),
            GroqAPIError("timeout"),
            GroqParseError("invalid JSON"),
            IdempotencyError("DB locked"),
        ]
        for exc in exceptions:
            with pytest.raises(AgentError):
                raise exc


class TestGitHubAPIError:
    def test_stores_status_code(self):
        err = GitHubAPIError(502, "Bad Gateway")
        assert err.status_code == 502

    def test_message_includes_status_code(self):
        err = GitHubAPIError(500, "Internal Server Error")
        assert "500" in str(err)
        assert "Internal Server Error" in str(err)


class TestGitHubRateLimitError:
    def test_default_message(self):
        err = GitHubRateLimitError()
        assert "Rate limit" in str(err)
        assert err.status_code == 429

    def test_custom_message(self):
        err = GitHubRateLimitError("API rate limit exceeded for user")
        assert "API rate limit exceeded" in str(err)


class TestGroqAPIError:
    def test_message(self):
        err = GroqAPIError("Connection timeout")
        assert "Connection timeout" in str(err)


class TestGroqParseError:
    def test_message(self):
        err = GroqParseError("Expected JSON, got HTML")
        assert "Expected JSON" in str(err)


class TestIdempotencyError:
    def test_message(self):
        err = IdempotencyError("database is locked")
        assert "database is locked" in str(err)

    def test_preserves_cause(self):
        import sqlite3
        cause = sqlite3.OperationalError("database is locked")
        err = IdempotencyError("DB error")
        err.__cause__ = cause
        assert err.__cause__ is cause


class TestExceptionChaining:
    def test_groq_api_error_chains_from_original(self):
        original = ConnectionError("timeout")
        err = GroqAPIError("Groq call failed")
        err.__cause__ = original
        assert err.__cause__ is original
        assert isinstance(err.__cause__, ConnectionError)

    def test_idempotency_error_chains_from_sqlite(self):
        import sqlite3
        original = sqlite3.OperationalError("disk I/O error")
        err = IdempotencyError(f"Failed: {original}")
        err.__cause__ = original
        assert isinstance(err.__cause__, sqlite3.OperationalError)
