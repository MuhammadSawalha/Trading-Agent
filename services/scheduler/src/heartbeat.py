from datetime import datetime, timedelta

_last_tick: datetime | None = None

def record_heartbeat(now: datetime) -> None:
    global _last_tick
    _last_tick = now

def is_healthy(now: datetime, max_staleness_seconds: int) -> bool:
    if _last_tick is None:
        return False
    return (now - _last_tick) <= timedelta(seconds=max_staleness_seconds)
