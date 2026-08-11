from datetime import datetime
from zoneinfo import ZoneInfo
from src.schedule_config import is_regular_market_hours, is_extended_hours, SCHEDULES

ET = ZoneInfo("America/New_York")

def test_regular_market_hours_930_to_400pm():
    assert is_regular_market_hours(datetime(2026, 1, 5, 10, 0, tzinfo=ET)) is True  # Monday
    assert is_regular_market_hours(datetime(2026, 1, 5, 9, 0, tzinfo=ET)) is False
    assert is_regular_market_hours(datetime(2026, 1, 5, 16, 30, tzinfo=ET)) is False

def test_regular_market_hours_excludes_weekends():
    assert is_regular_market_hours(datetime(2026, 1, 3, 10, 0, tzinfo=ET)) is False  # Saturday

def test_extended_hours_4am_to_8pm():
    assert is_extended_hours(datetime(2026, 1, 5, 5, 0, tzinfo=ET)) is True
    assert is_extended_hours(datetime(2026, 1, 5, 19, 59, tzinfo=ET)) is True
    assert is_extended_hours(datetime(2026, 1, 5, 3, 0, tzinfo=ET)) is False
    assert is_extended_hours(datetime(2026, 1, 5, 20, 1, tzinfo=ET)) is False

def test_discovery_schedule_matches_marketaux_regular_hours_cadence():
    assert SCHEDULES["discovery"].cadence_seconds_regular == SCHEDULES["marketaux"].cadence_seconds_regular == 1800
    assert SCHEDULES["discovery"].active_overnight is False

def test_marketaux_extended_hours_cadence_is_90_minutes():
    assert SCHEDULES["marketaux"].cadence_seconds_extended == 5400
    assert SCHEDULES["marketaux"].active_overnight is False

def test_discovery_has_no_separate_extended_tier_reuses_regular_cadence_throughout():
    # Per spec §7: discovery uses ONE flat 30-min cadence across the whole 4am-8pm window,
    # not Marketaux's separate 90-min pre/after-hours tier.
    assert SCHEDULES["discovery"].cadence_seconds_extended == SCHEDULES["discovery"].cadence_seconds_regular

def test_technical_options_schedule_matches_discovery_tier_precedent_not_finnhub_live():
    # TradingView-backed per-symbol technicals/options depend on the same circuit-breaker-
    # protected TradingView scanner infrastructure as the discovery tier (spec §7) — the risk
    # is total daily call volume against that one fragile shared dependency, not burst rate
    # (the sliding-window limiter already caps bursts regardless of which tier a tool is on).
    # 7 tools x 30 symbols at 5-min cadence is 40,000+ calls/day; at 30-min it's ~10,000/day,
    # matching the same reasoning and number already established for the discovery tier and
    # Marketaux's regular-hours cadence — reused here rather than introducing a new one.
    assert SCHEDULES["technical_options"].cadence_seconds_regular == SCHEDULES["discovery"].cadence_seconds_regular == 1800
    assert SCHEDULES["technical_options"].cadence_seconds_regular != SCHEDULES["finnhub_live"].cadence_seconds_regular
