from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gh_token: str
    gh_webhook_secret: str
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout: int = 60
    log_level: str = "INFO"
    max_diff_lines: int = 500
    idempotency_db_path: str = "/app/data/reviews.db"

    @field_validator("gh_token")
    @classmethod
    def gh_token_must_be_valid(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("GH_TOKEN must not be empty")
        valid_prefixes = ("ghp_", "ghs_", "gho_", "github_pat_")
        if not v.startswith(valid_prefixes):
            raise ValueError(
                f"GH_TOKEN must start with one of {valid_prefixes}"
            )
        return v

    @field_validator("gh_webhook_secret")
    @classmethod
    def webhook_secret_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("GH_WEBHOOK_SECRET must not be empty")
        return v

    @field_validator("groq_api_key")
    @classmethod
    def groq_api_key_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("GROQ_API_KEY must not be empty")
        return v

    @field_validator("groq_timeout")
    @classmethod
    def timeout_must_be_positive(cls, v: int) -> int:
        if v < 5:
            raise ValueError("GROQ_TIMEOUT must be >= 5 seconds")
        return v

    @field_validator("max_diff_lines")
    @classmethod
    def max_diff_lines_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("MAX_DIFF_LINES must be >= 1")
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
