from datetime import datetime, timezone
from src.rate_limit.daily_cap import DailyCapScheduler

def test_allows_up_to_cap_minus_safety_margin():
    sched = DailyCapScheduler(daily_cap=100, safety_margin=10)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    for _ in range(90):
        assert sched.allow(now) is True
    assert sched.allow(now) is False  # 90 used, cap is 100, margin 10 -> budget 90

def test_remaining_reflects_budget_used():
    sched = DailyCapScheduler(daily_cap=100, safety_margin=10)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert sched.remaining(now) == 90
    sched.allow(now)
    assert sched.remaining(now) == 89

def test_resets_at_utc_midnight():
    sched = DailyCapScheduler(daily_cap=1, safety_margin=0)
    day1 = datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)
    day2 = datetime(2026, 1, 2, 0, 1, tzinfo=timezone.utc)
    assert sched.allow(day1) is True
    assert sched.allow(day1) is False
    assert sched.allow(day2) is True
