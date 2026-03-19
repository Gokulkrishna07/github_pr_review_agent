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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
