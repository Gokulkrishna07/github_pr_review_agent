from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_app_id: str
    github_app_private_key: str
    gh_webhook_secret: str
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout: int = 60
    log_level: str = "INFO"
    max_diff_lines: int = 500
    idempotency_db_path: str = "/app/data/reviews.db"
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    session_secret_key: str = "change-me-in-production"
    frontend_url: str = ""
    config_db_path: str = "/app/data/config.db"

    @field_validator("github_app_id")
    @classmethod
    def app_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("GITHUB_APP_ID must not be empty")
        return v.strip()

    @field_validator("github_app_private_key")
    @classmethod
    def private_key_must_be_valid(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("GITHUB_APP_PRIVATE_KEY must not be empty")
        if "PRIVATE KEY" not in v:
            raise ValueError("GITHUB_APP_PRIVATE_KEY must contain a valid PEM private key")
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
