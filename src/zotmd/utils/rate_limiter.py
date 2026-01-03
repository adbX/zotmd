"""Rate limiter for API requests."""

import threading
import time
from collections import deque


class RateLimiter:
    """Simple sliding window rate limiter.

    Uses a sliding window to track request timestamps and throttle
    when approaching the rate limit.

    Args:
        max_requests: Maximum requests allowed per window
        window_seconds: Time window in seconds
        safety_margin: Fraction of limit to use as buffer (default 0.8 = 80%)
    """

    def __init__(
        self,
        max_requests: int = 120,
        window_seconds: float = 60.0,
        safety_margin: float = 0.8,
    ):
        self.max_requests = int(max_requests * safety_margin)
        self.window_seconds = window_seconds
        self.requests: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Acquire permission to make a request, blocking if necessary."""
        with self._lock:
            now = time.time()
            window_start = now - self.window_seconds

            # Remove requests outside the window
            while self.requests and self.requests[0] < window_start:
                self.requests.popleft()

            # If at limit, wait until oldest request expires
            if len(self.requests) >= self.max_requests:
                sleep_time = self.requests[0] - window_start
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    # Re-check after sleeping
                    now = time.time()
                    window_start = now - self.window_seconds
                    while self.requests and self.requests[0] < window_start:
                        self.requests.popleft()

            # Record this request
            self.requests.append(time.time())

    def get_current_usage(self) -> int:
        """Get current number of requests in the window."""
        with self._lock:
            now = time.time()
            window_start = now - self.window_seconds
            while self.requests and self.requests[0] < window_start:
                self.requests.popleft()
            return len(self.requests)
