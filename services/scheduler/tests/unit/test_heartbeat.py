from datetime import datetime, timedelta, timezone
import src.heartbeat as hb
from src.heartbeat import record_heartbeat, is_healthy, SCHEDULER_LAST_TICK_TIMESTAMP

def test_unhealthy_before_first_heartbeat():
    hb._last_tick = None
    assert is_healthy(datetime(2026, 1, 1, 12, 0), max_staleness_seconds=90) is False

def test_healthy_shortly_after_heartbeat():
    record_heartbeat(datetime(2026, 1, 1, 12, 0, 0))
    assert is_healthy(datetime(2026, 1, 1, 12, 0, 30), max_staleness_seconds=90) is True

def test_unhealthy_once_stale():
    record_heartbeat(datetime(2026, 1, 1, 12, 0, 0))
    assert is_healthy(datetime(2026, 1, 1, 12, 2, 0), max_staleness_seconds=90) is False

def test_record_heartbeat_sets_scheduler_last_tick_timestamp_gauge():
    # Task 55: feeds the SchedulerHeartbeatStale alert (time() - this gauge > 180).
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    record_heartbeat(now)
    assert SCHEDULER_LAST_TICK_TIMESTAMP._value.get() == now.timestamp()

def test_record_heartbeat_gauge_updates_on_each_call():
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=60)
    record_heartbeat(t0)
    assert SCHEDULER_LAST_TICK_TIMESTAMP._value.get() == t0.timestamp()
    record_heartbeat(t1)
    assert SCHEDULER_LAST_TICK_TIMESTAMP._value.get() == t1.timestamp()
