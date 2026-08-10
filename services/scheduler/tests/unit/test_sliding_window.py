from datetime import datetime, timedelta
from src.rate_limit.sliding_window import SlidingWindowLimiter

def test_allows_calls_up_to_max_within_window():
    limiter = SlidingWindowLimiter(max_calls=3, window_seconds=60)
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert limiter.allow(now) is True
    assert limiter.allow(now) is True
    assert limiter.allow(now) is True
    assert limiter.allow(now) is False

def test_old_calls_fall_out_of_window():
    limiter = SlidingWindowLimiter(max_calls=1, window_seconds=60)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    assert limiter.allow(t0) is True
    assert limiter.allow(t0 + timedelta(seconds=30)) is False
    assert limiter.allow(t0 + timedelta(seconds=61)) is True

def test_disallowed_calls_are_not_recorded():
    limiter = SlidingWindowLimiter(max_calls=1, window_seconds=60)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    limiter.allow(t0)
    limiter.allow(t0 + timedelta(seconds=1))  # rejected, must not count
    assert limiter.allow(t0 + timedelta(seconds=61)) is True
