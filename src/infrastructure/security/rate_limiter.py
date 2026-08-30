"""Sliding-window in-memory rate limiter per Telegram user."""

import time
from collections import defaultdict
from typing import Dict, List


class UserRateLimiter:
    """Track request frequency per user within a rolling 60-second window."""

    def __init__(self, max_requests_per_minute: int = 15):
        self.max_requests = max_requests_per_minute
        self._history: Dict[int, List[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> bool:
        """Return True if user has remaining quota within the current 60s window."""
        now = time.time()
        cutoff = now - 60.0

        # Purge timestamps older than 1 minute
        valid_timestamps = [ts for ts in self._history[user_id] if ts > cutoff]
        self._history[user_id] = valid_timestamps

        if len(valid_timestamps) >= self.max_requests:
            return False

        self._history[user_id].append(now)
        return True

    def get_remaining_quota(self, user_id: int) -> int:
        """Return remaining requests allowed in the active minute."""
        now = time.time()
        cutoff = now - 60.0
        valid_count = sum(1 for ts in self._history.get(user_id, []) if ts > cutoff)
        return max(0, self.max_requests - valid_count)

    def reset_user(self, user_id: int) -> None:
        """Clear rate limit history for a specific user."""
        self._history.pop(user_id, None)
