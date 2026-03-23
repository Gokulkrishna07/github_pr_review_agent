"""Central dispatcher — builds prompt, calls the selected provider, parses response."""

import logging

from ..prompts import build_review_prompt_with_config
from ..types import FileReview
from .base import parse_response
from .registry import PROVIDERS

logger = logging.getLogger(__name__)


async def review_diff(
    filename: str,
    patch: str,
    *,
    pr_title: str,
    pr_description: str,
    api_key: str,
    model: str,
    timeout: int,
    file_content: str | None = None,
    custom_template: str | None = None,
    provider_name: str = "groq",
) -> FileReview:
    """Send a diff to the selected LLM provider for review."""
    prompt = build_review_prompt_with_config(
        filename, patch,
        pr_title=pr_title,
        pr_description=pr_description,
        file_content=file_content,
        custom_template=custom_template,
    )

    cfg = PROVIDERS.get(provider_name)
    if not cfg or not cfg.module:
        raise ValueError(f"Unknown LLM provider: {provider_name}")

    text = await cfg.module.call_llm(
        prompt, model=model, api_key=api_key, timeout=timeout,
    )
    return parse_response(text)
