"""Rate limiter for YNAB API requests.

YNAB enforces a rate limit of 200 requests per rolling hour window.
This module tracks API requests and provides utilities to:
- Track requests with timestamps
- Check remaining quota
- Wait when approaching rate limit
- Persist state to disk for resuming across sessions
"""

import asyncio
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypedDict

# YNAB API rate limit: 200 requests per hour
RATE_LIMIT_REQUESTS = 200
RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour

# Safety margin: stop before hitting the hard limit
SAFETY_MARGIN = 10  # Leave 10 requests as buffer
EFFECTIVE_LIMIT = RATE_LIMIT_REQUESTS - SAFETY_MARGIN


class RateLimiterState(TypedDict):
    """Serializable state for the rate limiter."""

    request_timestamps: list[float]


class RateLimitExceeded(Exception):
    """Raised when rate limit would be exceeded."""

    def __init__(self, wait_seconds: float, remaining_requests: int):
        self.wait_seconds = wait_seconds
        self.remaining_requests = remaining_requests
        super().__init__(
            f"Rate limit reached. {remaining_requests} requests remaining. "
            f"Wait {wait_seconds:.0f} seconds before continuing."
        )


class RateLimiter:
    """Tracks API requests to stay within YNAB's rate limit.

    The rate limiter uses a rolling window approach, matching YNAB's implementation.
    Requests older than 1 hour are automatically pruned.
    """

    def __init__(
        self,
        state_file: Path | None = None,
        max_requests: int = EFFECTIVE_LIMIT,
        window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
    ):
        self._state_file = state_file or self._default_state_file()
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._request_timestamps: deque[float] = deque()
        self._load_state()

    @staticmethod
    def _default_state_file() -> Path:
        """Get the default state file path."""
        config_dir = Path.home() / ".config" / "ynab-cli"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "rate_limiter_state.json"

    def _load_state(self) -> None:
        """Load state from disk if available."""
        if self._state_file.exists():
            try:
                with self._state_file.open("r") as f:
                    data: RateLimiterState = json.load(f)
                    timestamps = data.get("request_timestamps", [])
                    # Only load timestamps within the current window
                    cutoff = time.time() - self._window_seconds
                    self._request_timestamps = deque(ts for ts in timestamps if ts > cutoff)
            except (json.JSONDecodeError, KeyError, TypeError):
                # If state is corrupted, start fresh
                self._request_timestamps = deque()

    def _save_state(self) -> None:
        """Persist state to disk."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        with self._state_file.open("w") as f:
            state: RateLimiterState = {"request_timestamps": list(self._request_timestamps)}
            json.dump(state, f)

    def _prune_old_requests(self) -> None:
        """Remove requests older than the rolling window."""
        cutoff = time.time() - self._window_seconds
        while self._request_timestamps and self._request_timestamps[0] <= cutoff:
            self._request_timestamps.popleft()

    @property
    def requests_in_window(self) -> int:
        """Number of requests made in the current window."""
        self._prune_old_requests()
        return len(self._request_timestamps)

    @property
    def remaining_requests(self) -> int:
        """Number of requests remaining in the current window."""
        return max(0, self._max_requests - self.requests_in_window)

    @property
    def seconds_until_next_slot(self) -> float:
        """Seconds until one request slot becomes available."""
        if self.remaining_requests > 0:
            return 0.0

        self._prune_old_requests()
        if not self._request_timestamps:
            return 0.0

        oldest_request = self._request_timestamps[0]
        wait_time = oldest_request + self._window_seconds - time.time()
        return max(0.0, wait_time)

    def can_make_request(self) -> bool:
        """Check if a request can be made without exceeding the limit."""
        return self.remaining_requests > 0

    def record_request(self) -> None:
        """Record that a request was made."""
        self._prune_old_requests()
        self._request_timestamps.append(time.time())
        self._save_state()

    async def acquire(
        self,
        auto_wait: bool = False,
        on_wait_start: Callable[[float], Awaitable[None]] | None = None,
        on_wait_progress: Callable[[float, float], Awaitable[None]] | None = None,
    ) -> None:
        """Acquire a request slot.

        Args:
            auto_wait: If True, automatically wait when rate limited.
                      If False, raise RateLimitExceeded.
            on_wait_start: Async callback called when waiting starts, with total wait seconds.
            on_wait_progress: Async callback called every minute during wait, with (elapsed, remaining) seconds.

        Raises:
            RateLimitExceeded: If rate limited and auto_wait is False.
        """
        self._prune_old_requests()

        if not self.can_make_request():
            wait_seconds = self.seconds_until_next_slot

            if auto_wait:
                if on_wait_start:
                    await on_wait_start(wait_seconds)

                # Wait in 60-second chunks to provide progress updates
                elapsed = 0.0
                while elapsed < wait_seconds:
                    chunk = min(60.0, wait_seconds - elapsed)
                    await asyncio.sleep(chunk)
                    elapsed += chunk

                    if on_wait_progress and elapsed < wait_seconds:
                        await on_wait_progress(elapsed, wait_seconds - elapsed)

                self._prune_old_requests()
            else:
                raise RateLimitExceeded(
                    wait_seconds=wait_seconds,
                    remaining_requests=self.remaining_requests,
                )

        self.record_request()

    def get_status_message(self) -> str:
        """Get a human-readable status message."""
        remaining = self.remaining_requests
        total = self._max_requests

        if remaining == 0:
            wait = self.seconds_until_next_slot
            minutes = int(wait // 60)
            seconds = int(wait % 60)
            return f"Rate limit reached (0/{total}). Next slot in {minutes}m {seconds}s."

        return f"API quota: {remaining}/{total} requests remaining in this hour."

    def reset(self) -> None:
        """Reset the rate limiter state (for testing or manual reset)."""
        self._request_timestamps.clear()
        self._save_state()

