import pytest
from pydantic import ValidationError

from agent.config import Settings


def _valid_env(**overrides) -> dict:
    """Return a minimal valid settings dict, with optional overrides."""
    base = {
        "gh_token": "ghp_validtoken1234567890",
        "gh_webhook_secret": "my-secret",
        "groq_api_key": "gsk_testapikey",
    }
    base.update(overrides)
    return base


class TestGhTokenValidation:
    def test_valid_ghp_prefix_accepted(self):
        s = Settings(**_valid_env(gh_token="ghp_abc123"))
        assert s.gh_token == "ghp_abc123"

    def test_valid_ghs_prefix_accepted(self):
        s = Settings(**_valid_env(gh_token="ghs_abc123"))
        assert s.gh_token == "ghs_abc123"

    def test_valid_gho_prefix_accepted(self):
        s = Settings(**_valid_env(gh_token="gho_abc123"))
        assert s.gh_token == "gho_abc123"

    def test_valid_github_pat_prefix_accepted(self):
        s = Settings(**_valid_env(gh_token="github_pat_abc123"))
        assert s.gh_token == "github_pat_abc123"

    def test_empty_token_rejected(self):
        with pytest.raises(ValidationError, match="GH_TOKEN must not be empty"):
            Settings(**_valid_env(gh_token=""))

    def test_whitespace_only_token_rejected(self):
        with pytest.raises(ValidationError, match="GH_TOKEN must not be empty"):
            Settings(**_valid_env(gh_token="   "))

    def test_invalid_prefix_rejected(self):
        with pytest.raises(ValidationError, match="GH_TOKEN must start with"):
            Settings(**_valid_env(gh_token="invalid-token"))


class TestWebhookSecretValidation:
    def test_valid_secret_accepted(self):
        s = Settings(**_valid_env(gh_webhook_secret="my-secret"))
        assert s.gh_webhook_secret == "my-secret"

    def test_empty_secret_rejected(self):
        with pytest.raises(ValidationError, match="GH_WEBHOOK_SECRET must not be empty"):
            Settings(**_valid_env(gh_webhook_secret=""))

    def test_whitespace_only_secret_rejected(self):
        with pytest.raises(ValidationError, match="GH_WEBHOOK_SECRET must not be empty"):
            Settings(**_valid_env(gh_webhook_secret="   "))


class TestGroqApiKeyValidation:
    def test_valid_key_accepted(self):
        s = Settings(**_valid_env(groq_api_key="gsk_key123"))
        assert s.groq_api_key == "gsk_key123"

    def test_empty_key_rejected(self):
        with pytest.raises(ValidationError, match="GROQ_API_KEY must not be empty"):
            Settings(**_valid_env(groq_api_key=""))

    def test_whitespace_only_key_rejected(self):
        with pytest.raises(ValidationError, match="GROQ_API_KEY must not be empty"):
            Settings(**_valid_env(groq_api_key="   "))


class TestGroqTimeoutValidation:
    def test_default_timeout_is_60(self):
        s = Settings(**_valid_env())
        assert s.groq_timeout == 60

    def test_valid_timeout_accepted(self):
        s = Settings(**_valid_env(groq_timeout=30))
        assert s.groq_timeout == 30

    def test_minimum_timeout_accepted(self):
        s = Settings(**_valid_env(groq_timeout=5))
        assert s.groq_timeout == 5

    def test_timeout_below_minimum_rejected(self):
        with pytest.raises(ValidationError, match="GROQ_TIMEOUT must be >= 5"):
            Settings(**_valid_env(groq_timeout=4))

    def test_zero_timeout_rejected(self):
        with pytest.raises(ValidationError, match="GROQ_TIMEOUT must be >= 5"):
            Settings(**_valid_env(groq_timeout=0))

    def test_negative_timeout_rejected(self):
        with pytest.raises(ValidationError, match="GROQ_TIMEOUT must be >= 5"):
            Settings(**_valid_env(groq_timeout=-1))


class TestMaxDiffLinesValidation:
    def test_default_is_500(self):
        s = Settings(**_valid_env())
        assert s.max_diff_lines == 500

    def test_valid_value_accepted(self):
        s = Settings(**_valid_env(max_diff_lines=100))
        assert s.max_diff_lines == 100

    def test_minimum_value_accepted(self):
        s = Settings(**_valid_env(max_diff_lines=1))
        assert s.max_diff_lines == 1

    def test_zero_rejected(self):
        with pytest.raises(ValidationError, match="MAX_DIFF_LINES must be >= 1"):
            Settings(**_valid_env(max_diff_lines=0))

    def test_negative_rejected(self):
        with pytest.raises(ValidationError, match="MAX_DIFF_LINES must be >= 1"):
            Settings(**_valid_env(max_diff_lines=-10))
