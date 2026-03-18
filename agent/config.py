from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_token: str
    github_webhook_secret: str
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    ollama_timeout: int = 120
    log_level: str = "INFO"
    max_diff_lines: int = 500

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
