from datetime import datetime, timedelta
from prometheus_client import Gauge

_last_tick: datetime | None = None

# Task 55: feeds the SchedulerHeartbeatStale alert (monitoring/prometheus/rules/alerts.yaml),
# which fires when time() - this gauge exceeds 180s. The scheduler is a deliberate
# single-replica SPOF (spec §10), so a stalled loop needs to be visible to Prometheus, not
# just to /healthz.
SCHEDULER_LAST_TICK_TIMESTAMP = Gauge(
    "scheduler_last_tick_timestamp_seconds",
    "Unix timestamp of the scheduler's last completed tick",
)

def record_heartbeat(now: datetime) -> None:
    global _last_tick
    _last_tick = now
    SCHEDULER_LAST_TICK_TIMESTAMP.set(now.timestamp())

def is_healthy(now: datetime, max_staleness_seconds: int) -> bool:
    if _last_tick is None:
        return False
    return (now - _last_tick) <= timedelta(seconds=max_staleness_seconds)
