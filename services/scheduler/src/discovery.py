from datetime import datetime
from .mcp_clients import call_tool
from .schedule_config import is_extended_hours, SCHEDULES, MAX_NON_TRADING_GAP_SECONDS
from common.dynamo import write_tool_result, record_fetch_attempt, get_last_fetch_attempt

# Real tool names verified against each live server (neither had a "*_screener" tool -- that
# was a guess that never matched). top_gainers/top_losers default to a crypto exchange
# (KUCOIN) when no `exchange` is given; NASDAQ matches this app's equities-only watchlist.
# top_volume/volume_breakout already default to "major US exchanges" with no override needed.
DISCOVERY_TOOLS: dict[str, tuple[str, str, dict]] = {
    "top_gainers": ("tradingview", "top_gainers", {"exchange": "NASDAQ"}),
    "top_losers": ("tradingview", "top_losers", {"exchange": "NASDAQ"}),
    "top_volume": ("stock_scanner", "tradingview_top_volume", {}),
    "volume_breakout": ("stock_scanner", "tradingview_volume_breakout", {}),
}
# Paused 8pm-4am ET (and weekends) below, same as every other active_overnight=False schedule --
# must survive that pause, not just the 30-min in-window cadence, or the dashboards go blank
# overnight. See MAX_NON_TRADING_GAP_SECONDS.
_DISCOVERY_TTL_SECONDS = MAX_NON_TRADING_GAP_SECONDS
# All 4 dashboards fetch together as one pass, so cadence is tracked with a single shared pk
# rather than one per dashboard.
_DISCOVERY_LAST_FETCH_PK = "DISCOVERY#LAST_FETCH"

async def fetch_discovery_dashboards(mcp_client, now_et: datetime) -> None:
    if not is_extended_hours(now_et):  # paused 8pm-4am ET, per spec §7
        return

    cadence_seconds = SCHEDULES["discovery"].cadence_seconds_regular
    last_attempt = get_last_fetch_attempt(_DISCOVERY_LAST_FETCH_PK)
    if last_attempt is not None and (now_et - last_attempt).total_seconds() < cadence_seconds:
        return  # not due yet -- avoid hammering the shared TradingView/stock_scanner upstream

    for dashboard_name, (server, tool_name, params) in DISCOVERY_TOOLS.items():
        result = await call_tool(mcp_client, server, tool_name, **params)
        write_tool_result(f"DASHBOARD#{dashboard_name}", result, ttl_seconds=_DISCOVERY_TTL_SECONDS)

    record_fetch_attempt(_DISCOVERY_LAST_FETCH_PK, now_et)
