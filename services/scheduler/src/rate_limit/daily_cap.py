from datetime import datetime

class DailyCapScheduler:
    def __init__(self, daily_cap: int, safety_margin: int):
        self._budget = daily_cap - safety_margin
        self._used = 0
        self._current_day: str | None = None

    def _roll_if_new_day(self, now: datetime) -> None:
        day_key = now.date().isoformat()
        if day_key != self._current_day:
            self._current_day = day_key
            self._used = 0

    def allow(self, now: datetime) -> bool:
        self._roll_if_new_day(now)
        if self._used >= self._budget:
            return False
        self._used += 1
        return True

    def remaining(self, now: datetime) -> int:
        self._roll_if_new_day(now)
        return self._budget - self._used
