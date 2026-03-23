"""Groq LLM provider using the groq SDK."""

import asyncio
import logging
import time

from groq import AsyncGroq

from ..exceptions import GroqAPIError
from ..metrics import groq_request_duration_seconds, groq_requests_total, llm_tokens_used_total

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_shared_client: AsyncGroq | None = None


def _get_client(api_key: str, timeout: int) -> AsyncGroq:
    global _shared_client
    if _shared_client is None:
        _shared_client = AsyncGroq(api_key=api_key, timeout=timeout)
    return _shared_client


async def call_llm(prompt: str, *, model: str, api_key: str, timeout: int) -> str:
    """Send prompt to Groq, return raw text response."""
    client = _get_client(api_key, timeout)
    start = time.monotonic()
    last_error: Exception | None = None

    try:
        for attempt in range(MAX_RETRIES):
            try:
                completion = await client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=model,
                    temperature=0.2,
                    max_tokens=1024,
                )
                groq_requests_total.labels(status="success").inc()
                break
            except Exception as e:
                last_error = e
                status_code = getattr(e, "status_code", None)
                if status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "Groq API error (status %s), retrying in %ds (%d/%d)...",
                        status_code, wait, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    continue
                groq_requests_total.labels(status="error").inc()
                raise GroqAPIError(f"Groq API call failed: {e}") from e
        else:
            groq_requests_total.labels(status="error").inc()
            raise GroqAPIError(f"Groq API failed after {MAX_RETRIES} retries: {last_error}") from last_error
    finally:
        groq_request_duration_seconds.observe(time.monotonic() - start)

    usage = getattr(completion, "usage", None)
    if usage:
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        if prompt_tokens:
            llm_tokens_used_total.labels(type="prompt").inc(prompt_tokens)
        if completion_tokens:
            llm_tokens_used_total.labels(type="completion").inc(completion_tokens)

    return completion.choices[0].message.content or ""
