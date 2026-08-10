from datetime import datetime, timedelta
from src.rate_limit.circuit_breaker import CircuitBreaker

def test_starts_closed_and_allows_calls():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert cb.state == "closed"
    assert cb.allow_call(now) is True

def test_trips_open_after_threshold_consecutive_failures():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    now = datetime(2026, 1, 1, 12, 0, 0)
    cb.record_failure(now)
    cb.record_failure(now)
    assert cb.state == "closed"
    cb.record_failure(now)
    assert cb.state == "open"
    assert cb.allow_call(now) is False

def test_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    now = datetime(2026, 1, 1, 12, 0, 0)
    cb.record_failure(now)
    cb.record_failure(now)
    cb.record_success(now)
    cb.record_failure(now)
    cb.record_failure(now)
    assert cb.state == "closed"  # only 2 consecutive since the success reset it

def test_moves_to_half_open_after_cooldown_then_closes_on_success():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    cb.record_failure(t0)
    assert cb.state == "open"
    assert cb.allow_call(t0 + timedelta(seconds=30)) is False  # still cooling down
    assert cb.allow_call(t0 + timedelta(seconds=61)) is True  # half-open, allows a probe call
    assert cb.state == "half_open"
    cb.record_success(t0 + timedelta(seconds=61))
    assert cb.state == "closed"

def test_half_open_failure_reopens_and_restarts_cooldown():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    cb.record_failure(t0)
    cb.allow_call(t0 + timedelta(seconds=61))  # half-open probe
    cb.record_failure(t0 + timedelta(seconds=61))
    assert cb.state == "open"
    assert cb.allow_call(t0 + timedelta(seconds=90)) is False  # cooldown restarted from t0+61
