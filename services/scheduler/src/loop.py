import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .discovery import fetch_discovery_dashboards
from .input_data_agent import run_input_data_agent_for_symbol, FETCH_PLAN
from .graph.build_graph import build_graph
from common.dynamo import read_watchlist, read_tool_result

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")
_graph = None  # built lazily, once, on first tick

def _build_tool_data(symbol: str) -> dict[str, dict]:
    """Reassembles the per-specialist tool_data dict the graph expects (specialists.py reads
    state["tool_data"][specialist_name]) by reading back everything run_input_data_agent_for_symbol
    already wrote to DynamoDB for this symbol's FETCH_PLAN entries. Skips any pk not yet fetched."""
    tool_data: dict[str, dict] = {}
    for spec in FETCH_PLAN:
        pk = f"{symbol}#{spec.tool_name}" if spec.per_symbol else f"GLOBAL#{spec.tool_name}"
        payload = read_tool_result(pk)
        if payload is None:
            continue
        tool_data.setdefault(spec.specialist, {})[spec.tool_name] = payload
    return tool_data

async def scheduler_tick(mcp_client, now_utc: datetime, now_et: datetime, previously_seen: set[str]) -> set[str]:
    global _graph
    if _graph is None:
        _graph = build_graph()

    try:
        await fetch_discovery_dashboards(mcp_client, now_et)
    except Exception:
        # The discovery-tier fetch talks to the same circuit-breaker-protected shared
        # TradingView/stock_scanner upstream (spec §7) -- a CircuitOpenError or any other
        # failure here is unrelated to any individual symbol's data and must not block the
        # per-symbol watchlist processing below (spec §10).
        logger.exception("discovery-tier fetch failed; continuing with watchlist processing")

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
                "tool_data": _build_tool_data(symbol),
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
