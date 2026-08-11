from datetime import datetime
from .mcp_clients import call_tool
from .schedule_config import is_extended_hours, SCHEDULES
from common.dynamo import write_tool_result, record_fetch_attempt, get_last_fetch_attempt

DISCOVERY_TOOLS: dict[str, tuple[str, str]] = {
    "top_gainers": ("tradingview", "top_gainers_screener"),
    "top_losers": ("tradingview", "top_losers_screener"),
    "top_volume": ("stock_scanner", "tradingview_top_volume"),
    "volume_breakout": ("stock_scanner", "tradingview_volume_breakout"),
}
_DISCOVERY_TTL_SECONDS = 1800  # matches the 30-min discovery-tier cadence, spec §7
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

    for dashboard_name, (server, tool_name) in DISCOVERY_TOOLS.items():
        result = await call_tool(mcp_client, server, tool_name)
        write_tool_result(f"DASHBOARD#{dashboard_name}", result, ttl_seconds=_DISCOVERY_TTL_SECONDS)

    record_fetch_attempt(_DISCOVERY_LAST_FETCH_PK, now_et)
