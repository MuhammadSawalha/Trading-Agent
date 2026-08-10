from datetime import datetime, timedelta
from typing import Literal

class CircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_seconds: float):
        self._threshold = failure_threshold
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._consecutive_failures = 0
        self._state: Literal["closed", "open", "half_open"] = "closed"
        self._opened_at: datetime | None = None

    @property
    def state(self) -> Literal["closed", "open", "half_open"]:
        return self._state

    def allow_call(self, now: datetime) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            assert self._opened_at is not None
            if now - self._opened_at >= self._cooldown:
                self._state = "half_open"
                return True
            return False
        return True  # half_open: allow the single probe call

    def record_success(self, now: datetime) -> None:
        self._consecutive_failures = 0
        self._state = "closed"
        self._opened_at = None

    def record_failure(self, now: datetime) -> None:
        self._consecutive_failures += 1
        if self._state == "half_open" or self._consecutive_failures >= self._threshold:
            self._state = "open"
            self._opened_at = now
