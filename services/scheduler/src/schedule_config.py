from dataclasses import dataclass
from datetime import datetime, time

_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)
_EXTENDED_OPEN = time(4, 0)
_EXTENDED_CLOSE = time(20, 0)

def is_regular_market_hours(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    return _REGULAR_OPEN <= now_et.time() < _REGULAR_CLOSE

def is_extended_hours(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    return _EXTENDED_OPEN <= now_et.time() < _EXTENDED_CLOSE

@dataclass(frozen=True)
class ProviderSchedule:
    cadence_seconds_regular: int
    cadence_seconds_extended: int | None  # None => not polled outside regular hours
    active_overnight: bool

SCHEDULES: dict[str, ProviderSchedule] = {
    "marketaux": ProviderSchedule(cadence_seconds_regular=1800, cadence_seconds_extended=5400, active_overnight=False),
    "fmp": ProviderSchedule(cadence_seconds_regular=86400, cadence_seconds_extended=None, active_overnight=False),
    "finnhub_static": ProviderSchedule(cadence_seconds_regular=86400, cadence_seconds_extended=None, active_overnight=False),
    "finnhub_live": ProviderSchedule(cadence_seconds_regular=60, cadence_seconds_extended=60, active_overnight=False),
    "fred_slow": ProviderSchedule(cadence_seconds_regular=86400, cadence_seconds_extended=None, active_overnight=False),
    "fred_vix": ProviderSchedule(cadence_seconds_regular=3600, cadence_seconds_extended=None, active_overnight=False),
    # TradingView-backed per-symbol technicals/options (Full Technical Analysis, Options
    # Chain, etc., Task 16): a different provider from Finnhub, with no per-minute quota of
    # its own but the same circuit-breaker-protected, fragile shared upstream as the discovery
    # tier below (Task 5) — the risk here is total daily call volume against that one
    # dependency, not burst rate (the sliding-window limiter already caps bursts independent
    # of schedule tier). No stated reason per-symbol technicals need fresher data than
    # discovery's market-wide context does, so this reuses the same 30-min number already
    # established for the discovery tier and Marketaux's regular-hours cadence, rather than
    # introducing a new one.
    "technical_options": ProviderSchedule(cadence_seconds_regular=1800, cadence_seconds_extended=None, active_overnight=False),
    # Discovery tier: flat 30-min cadence across the whole 4am-8pm extended window, reusing
    # Marketaux's regular-hours number per spec §7 rather than introducing a separate tier.
    "discovery": ProviderSchedule(cadence_seconds_regular=1800, cadence_seconds_extended=1800, active_overnight=False),
}
