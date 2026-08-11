from datetime import datetime
from .mcp_clients import call_tool
from .schedule_config import is_extended_hours
from common.dynamo import write_tool_result

DISCOVERY_TOOLS: dict[str, tuple[str, str]] = {
    "top_gainers": ("tradingview", "top_gainers_screener"),
    "top_losers": ("tradingview", "top_losers_screener"),
    "top_volume": ("stock_scanner", "tradingview_top_volume"),
    "volume_breakout": ("stock_scanner", "tradingview_volume_breakout"),
}
_DISCOVERY_TTL_SECONDS = 1800  # matches the 30-min discovery-tier cadence, spec §7

async def fetch_discovery_dashboards(mcp_client, now_et: datetime) -> None:
    if not is_extended_hours(now_et):  # paused 8pm-4am ET, per spec §7
        return
    for dashboard_name, (server, tool_name) in DISCOVERY_TOOLS.items():
        result = await call_tool(mcp_client, server, tool_name)
        write_tool_result(f"DASHBOARD#{dashboard_name}", result, ttl_seconds=_DISCOVERY_TTL_SECONDS)
