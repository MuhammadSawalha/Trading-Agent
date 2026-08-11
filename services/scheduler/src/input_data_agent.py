from dataclasses import dataclass, field
from datetime import date, datetime

def diff_changed(previous: dict | None, current: dict, is_news: bool) -> bool:
    if previous is None:
        return True
    if is_news:
        prev_uuids = {a["uuid"] for a in previous.get("data", [])}
        curr_uuids = {a["uuid"] for a in current.get("data", [])}
        return prev_uuids != curr_uuids
    return previous != current

_FMP_ROTATION_DAYS = 3

def fmp_is_due_today(symbol: str, watchlist: list[str], today: date) -> bool:
    group = watchlist.index(symbol) % _FMP_ROTATION_DAYS
    return group == today.toordinal() % _FMP_ROTATION_DAYS

@dataclass(frozen=True)
class FetchSpec:
    tool_name: str
    server: str  # "own" | "tradingview" | "stock_scanner"
    specialist: str  # "fundamentals" | "technical" | "sentiment" | "macro_options"
    schedule_key: str
    per_symbol: bool
    is_news: bool = False

FETCH_PLAN: list[FetchSpec] = [
    # Fundamentals — Finnhub static (9)
    FetchSpec("finnhub_company_profile", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_peers", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_basic_financials", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_earnings_calendar", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_earnings_surprises", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_insider_transactions", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_insider_sentiment", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_lobbying_data", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_usa_spending", "own", "fundamentals", "finnhub_static", True),
    # Fundamentals — FMP per-symbol (7, on the 3-day rotation) + global calendars (2)
    FetchSpec("fmp_income_statement", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_balance_sheet_statement", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_cash_flow_statement", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_financial_ratios", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_key_metrics", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_dcf_valuation", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_ratings_snapshot", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_dividends_calendar", "own", "fundamentals", "fmp", False),
    FetchSpec("fmp_stock_splits_calendar", "own", "fundamentals", "fmp", False),
    # Sentiment — Marketaux (news-diff by UUID) + Finnhub company news
    FetchSpec("marketaux_news_all", "own", "sentiment", "marketaux", True, is_news=True),
    FetchSpec("finnhub_company_news", "own", "sentiment", "finnhub_live", True, is_news=True),
    # Technical — Finnhub quote uses finnhub_live (its own per-minute quota, sliding-window
    # limited). TradingView-backed per-symbol technicals are a DIFFERENT provider with no
    # per-minute quota of its own but the same circuit-breaker-protected shared upstream as
    # the discovery tier (spec §7) — they get their own "technical_options" cadence tier
    # (Task 15, 30 min, matching the discovery-tier/Marketaux precedent), not finnhub_live's,
    # since the risk against that shared dependency is total daily call volume, not burst
    # rate. Still protected by the shared circuit breaker since server != "own".
    FetchSpec("finnhub_quote", "own", "technical", "finnhub_live", True),
    FetchSpec("full_technical_analysis", "tradingview", "technical", "technical_options", True),
    FetchSpec("multi_timeframe_analysis", "tradingview", "technical", "technical_options", True),
    FetchSpec("volume_confirmation_analysis", "tradingview", "technical", "technical_options", True),
    FetchSpec("candlestick_pattern_analysis", "tradingview", "technical", "technical_options", True),
    FetchSpec("tradingview_technicals", "stock_scanner", "technical", "technical_options", True),
    # Macro/Options — FRED series (global, not per-symbol) + TradingView options (per-symbol,
    # same 30-min technical_options cadence tier as the technicals above, for the same reason)
    FetchSpec("fred_federal_funds_rate", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_10y_treasury_yield", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_2y_treasury_yield", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_cpi", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_unemployment_rate", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_nonfarm_payrolls", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_real_gdp", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_consumer_sentiment", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_vix", "own", "macro_options", "fred_vix", False),
    FetchSpec("fmp_economic_indicators", "own", "macro_options", "fmp", False),
    FetchSpec("options_chain", "tradingview", "macro_options", "technical_options", True),
    FetchSpec("unusual_options_activity", "tradingview", "macro_options", "technical_options", True),
]

import logging
from .mcp_clients import call_tool
from common.dynamo import (
    read_tool_result, write_tool_result, append_process_history,
    record_fetch_attempt, get_last_fetch_attempt,
)
from .schedule_config import SCHEDULES, is_regular_market_hours, is_extended_hours
from .rate_limit.sliding_window import SlidingWindowLimiter
from .rate_limit.daily_cap import DailyCapScheduler

logger = logging.getLogger(__name__)

_TTL_SECONDS = {
    "marketaux": 1800, "fmp": 3 * 86400, "finnhub_static": 86400,
    "finnhub_live": 60, "fred_slow": 86400, "fred_vix": 3600, "technical_options": 1800,
}

@dataclass
class InputDataAgentResult:
    changed_specialists: set[str] = field(default_factory=set)
    is_new_symbol: bool = False

# Finnhub's real constraint is per-minute (60 calls/min free tier), not daily, so it's
# protected by a sliding window rather than a budget (spec §7). Marketaux's cadence/batching
# keeps it comfortably under its daily cap; this daily cap is the "protective safety cap as a
# backstop" spec §7 calls for on top of that, shared across the whole watchlist.
_finnhub_live_limiter = SlidingWindowLimiter(max_calls=55, window_seconds=60)
_marketaux_daily_backstop = DailyCapScheduler(daily_cap=100, safety_margin=10)

def _is_due(spec: FetchSpec, pk: str, now_utc: datetime, now_et: datetime, is_new_symbol: bool) -> bool:
    if is_new_symbol:
        return True
    schedule = SCHEDULES[spec.schedule_key]
    if not schedule.active_overnight and not is_extended_hours(now_et):
        return False

    if spec.schedule_key == "finnhub_live":
        return _finnhub_live_limiter.allow(now_utc)  # per-minute budget; false = skip this tick
    if spec.schedule_key == "marketaux":
        return _marketaux_daily_backstop.allow(now_utc)  # daily backstop; false = skip until UTC midnight

    # Every other schedule-driven tool (fmp, finnhub_static, fred_slow, fred_vix,
    # technical_options) has no dedicated rate limiter of its own, so cadence is enforced
    # directly here: has enough time actually elapsed since the last successful fetch attempt?
    # (This was the bug: previously this function only checked "is it market/extended hours",
    # which is True on every one of the Scheduler's 60s ticks — meaning finnhub_static's 11
    # daily tools, for example, would have been called once per minute per symbol instead of
    # once per day, directly contradicting spec §7's per-provider cadences.)
    last_attempt = get_last_fetch_attempt(pk)
    if last_attempt is None:
        return True
    if schedule.cadence_seconds_extended is not None and is_extended_hours(now_et) and not is_regular_market_hours(now_et):
        cadence = schedule.cadence_seconds_extended
    else:
        cadence = schedule.cadence_seconds_regular
    return (now_utc - last_attempt).total_seconds() >= cadence

async def run_input_data_agent_for_symbol(
    mcp_client, symbol: str, watchlist: list[str], is_new_symbol: bool,
    now_utc: datetime, now_et: datetime,
) -> InputDataAgentResult:
    result = InputDataAgentResult(is_new_symbol=is_new_symbol)

    for spec in FETCH_PLAN:
        pk = f"{symbol}#{spec.tool_name}" if spec.per_symbol else f"GLOBAL#{spec.tool_name}"

        if spec.per_symbol and spec.schedule_key == "fmp" and not is_new_symbol:
            # fmp_is_due_today's 3-day rotation already spaces a given symbol's FMP calls
            # ~3 days apart, comfortably wider than fmp's own 1-day generic cadence below — so
            # the two checks are complementary (rotation picks the day, cadence is a no-op
            # backstop on that day), not in conflict or bypassing one another.
            if not fmp_is_due_today(symbol, watchlist, now_utc.date()):
                continue
        if not _is_due(spec, pk, now_utc, now_et, is_new_symbol):
            continue

        params = {"symbol": symbol} if spec.per_symbol else {}
        try:
            current = await call_tool(mcp_client, spec.server, spec.tool_name, **params)
        except Exception:
            # One tool failing (e.g. Marketaux unreachable) must never block the rest of this
            # symbol's scheduled fetches (spec §10) — skip it, retry on the next tick. Deliberately
            # do NOT record a fetch attempt here: a failed call shouldn't push the next retry a
            # full cadence period out, only a successful one should reset that clock.
            logger.warning("fetch failed for %s/%s, will retry next tick", symbol, spec.tool_name, exc_info=True)
            continue

        record_fetch_attempt(pk, now_utc)
        previous = read_tool_result(pk)

        if diff_changed(previous, current, is_news=spec.is_news):
            write_tool_result(pk, current, ttl_seconds=_TTL_SECONDS[spec.schedule_key])
            result.changed_specialists.add(spec.specialist)
            append_process_history(
                symbol, spec.specialist,
                reason="new_symbol" if is_new_symbol else ("news_cascade" if spec.is_news else "scheduled_refresh"),
                status="finished", timestamp=now_utc,
            )

    return result

async def cross_check_analyst_price_targets(mcp_client, symbol: str) -> dict:
    """Cross-checks FMP's ratings/price-target data against TradingView's technical-analysis
    pivot-based target levels, since a single source can carry an outlier estimate. Field
    names on both sides should be confirmed against each provider's live response schema
    during implementation — this wires the two calls and the comparison, not the exact keys."""
    fmp_result = await call_tool(mcp_client, "own", "fmp_ratings_snapshot", symbol=symbol)
    tv_result = await call_tool(mcp_client, "tradingview", "full_technical_analysis", symbol=symbol)
    fmp_target = fmp_result.get("price_target")
    tv_target = tv_result.get("price_target")
    diverges = (
        fmp_target is not None and tv_target is not None
        and abs(fmp_target - tv_target) / max(fmp_target, tv_target) > 0.15
    )
    return {"fmp_target": fmp_target, "tradingview_target": tv_target, "diverges": diverges}
