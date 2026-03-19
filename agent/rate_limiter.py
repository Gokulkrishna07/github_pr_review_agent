import asyncio
import time


class RateLimiter:
    """Token bucket rate limiter for outbound API calls."""

    def __init__(self, max_calls: int, period: float):
        self._max_calls = max_calls
        self._period = period
        self._calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._calls = [t for t in self._calls if now - t < self._period]
            if len(self._calls) >= self._max_calls:
                wait = self._period - (now - self._calls[0])
                await asyncio.sleep(wait)
            self._calls.append(time.monotonic())
