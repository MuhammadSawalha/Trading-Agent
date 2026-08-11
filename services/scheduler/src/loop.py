import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .discovery import fetch_discovery_dashboards
from .input_data_agent import run_input_data_agent_for_symbol
from .graph.build_graph import build_graph
from common.dynamo import read_watchlist

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")
_graph = None  # built lazily, once, on first tick

async def scheduler_tick(mcp_client, now_utc: datetime, now_et: datetime, previously_seen: set[str]) -> set[str]:
    global _graph
    if _graph is None:
        _graph = build_graph()

    await fetch_discovery_dashboards(mcp_client, now_et)

    watchlist = read_watchlist()
    seen = set(previously_seen)

    for symbol in watchlist:
        is_new = symbol not in seen
        seen.add(symbol)

        try:
            result = await run_input_data_agent_for_symbol(mcp_client, symbol, watchlist, is_new, now_utc, now_et)
            if not result.changed_specialists:
                continue
            await _graph.ainvoke({
                "symbol": symbol, "mcp_client": mcp_client,
                "is_new_symbol": result.is_new_symbol,
                "changed_specialists": result.changed_specialists,
                "tool_data": {},
            })
        except Exception:
            # One symbol's fetch or pipeline run failing (including a Risk agent that never
            # passes its neutrality check, Task 20's RiskSchemaViolation) must never stop the
            # rest of the watchlist from being processed this tick (spec §10) — the last good
            # cached output for this symbol stays visible; log and move to the next symbol.
            logger.exception("input data agent or pipeline run failed for %s, skipping this tick", symbol)
            continue

    return seen

async def run_forever(mcp_client, tick_interval_seconds: int = 60) -> None:
    seen: set[str] = set()
    while True:
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(_ET)
        try:
            seen = await scheduler_tick(mcp_client, now_utc, now_et, seen)
        except Exception:
            logger.exception("scheduler tick failed; will retry next interval")
        await asyncio.sleep(tick_interval_seconds)
