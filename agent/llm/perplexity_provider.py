"""Perplexity provider via OpenAI-compatible endpoint."""

import asyncio
import logging
import time

import httpx

from ..exceptions import LLMAPIError
from ..metrics import llm_tokens_used_total

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
BASE_URL = "https://api.perplexity.ai/chat/completions"


async def call_llm(prompt: str, *, model: str, api_key: str, timeout: int) -> str:
    """Send prompt to Perplexity, return raw text response."""
    last_error: Exception | None = None
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(
                    BASE_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 1024,
                    },
                )
                if resp.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "Perplexity API %d, retrying in %ds (%d/%d)...",
                        resp.status_code, wait, attempt + 1, MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code != 200:
                    raise LLMAPIError(f"Perplexity API returned {resp.status_code}: {resp.text[:200]}")

                data = resp.json()
                text = data["choices"][0]["message"]["content"]

                usage = data.get("usage", {})
                if usage.get("prompt_tokens"):
                    llm_tokens_used_total.labels(type="prompt").inc(usage["prompt_tokens"])
                if usage.get("completion_tokens"):
                    llm_tokens_used_total.labels(type="completion").inc(usage["completion_tokens"])

                logger.debug("Perplexity call took %.1fs", time.monotonic() - start)
                return text

            except httpx.HTTPError as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Perplexity HTTP error, retrying in %ds: %s", wait, e)
                    await asyncio.sleep(wait)
                    continue
                raise LLMAPIError(f"Perplexity API failed: {e}") from e

    raise LLMAPIError(f"Perplexity API failed after {MAX_RETRIES} retries: {last_error}") from last_error
