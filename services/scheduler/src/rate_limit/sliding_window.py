from collections import deque
from datetime import datetime, timedelta

class SlidingWindowLimiter:
    def __init__(self, max_calls: int, window_seconds: float):
        self._max_calls = max_calls
        self._window = timedelta(seconds=window_seconds)
        self._calls: deque[datetime] = deque()

    def allow(self, now: datetime) -> bool:
        cutoff = now - self._window
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()
        if len(self._calls) >= self._max_calls:
            return False
        self._calls.append(now)
        return True
