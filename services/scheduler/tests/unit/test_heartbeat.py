from datetime import datetime, timedelta
from src.heartbeat import record_heartbeat, is_healthy

def test_unhealthy_before_first_heartbeat():
    import src.heartbeat as hb
    hb._last_tick = None
    assert is_healthy(datetime(2026, 1, 1, 12, 0), max_staleness_seconds=90) is False

def test_healthy_shortly_after_heartbeat():
    record_heartbeat(datetime(2026, 1, 1, 12, 0, 0))
    assert is_healthy(datetime(2026, 1, 1, 12, 0, 30), max_staleness_seconds=90) is True

def test_unhealthy_once_stale():
    record_heartbeat(datetime(2026, 1, 1, 12, 0, 0))
    assert is_healthy(datetime(2026, 1, 1, 12, 2, 0), max_staleness_seconds=90) is False
