import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .discovery import fetch_discovery_dashboards
from .input_data_agent import run_input_data_agent_for_symbol, FETCH_PLAN
from .graph.build_graph import build_graph
from .heartbeat import record_heartbeat
from common.dynamo import read_watchlist, read_tool_result, read_agent_output

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")
_graph = None  # built lazily, once, on first tick

def _seed_seen_symbols() -> set[str]:
    """Symbols that already have a Manager verdict have already been through the pipeline at
    least once, so they're not "new" for run_forever's purposes. Seeding `seen` from this
    durable state on startup keeps a process restart (deploy, crash, pod reschedule) from
    treating the whole watchlist as brand-new -- which would bypass cadence/extended-hours
    gating for every symbol at once (_is_due short-circuits to True for is_new_symbol=True)
    and fire a large burst of MCP/LLM calls in the first tick after every restart."""
    return {symbol for symbol in read_watchlist() if read_agent_output(symbol, "Manager") is not None}

def _read_global_tool_data() -> dict[str, dict]:
    """The per_symbol=False FETCH_PLAN entries (FRED series, fmp_economic_indicators, the FMP
    calendars, etc.) all resolve to the same GLOBAL#{tool_name} pk regardless of which symbol
    is being processed -- read them once per tick here rather than once per symbol."""
    tool_data: dict[str, dict] = {}
    for spec in FETCH_PLAN:
        if spec.per_symbol:
            continue
        payload = read_tool_result(f"GLOBAL#{spec.tool_name}")
        if payload is None:
            logger.debug("no cached result yet for global tool %s (specialist=%s)", spec.tool_name, spec.specialist)
            continue
        tool_data.setdefault(spec.specialist, {})[spec.tool_name] = payload
    return tool_data

def _read_symbol_tool_data(symbol: str, global_tool_data: dict[str, dict]) -> dict[str, dict]:
    """Reassembles the per-specialist tool_data dict the graph expects (specialists.py reads
    state["tool_data"][specialist_name]) by reading back this symbol's own per-symbol
    FETCH_PLAN entries and merging them on top of the tick's already-hoisted global_tool_data
    (copied per specialist so mutating one symbol's dict never leaks into another's)."""
    tool_data = {specialist: dict(tools) for specialist, tools in global_tool_data.items()}
    for spec in FETCH_PLAN:
        if not spec.per_symbol:
            continue
        pk = f"{symbol}#{spec.tool_name}"
        payload = read_tool_result(pk)
        if payload is None:
            # Expected and self-healing: TTLs match fetch cadences and write_tool_result only
            # writes on a diff, so a sibling tool-result row can be transiently absent even
            # while this specialist is in changed_specialists. Not a warning -- just makes a
            # partial-data specialist run diagnosable from logs after the fact.
            logger.debug(
                "no cached result yet for %s/%s (specialist=%s)", symbol, spec.tool_name, spec.specialist
            )
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
    global_tool_data: dict[str, dict] | None = None  # computed once, lazily, on first symbol that needs it

    for symbol in watchlist:
        is_new = symbol not in seen
        seen.add(symbol)

        try:
            result = await run_input_data_agent_for_symbol(mcp_client, symbol, watchlist, is_new, now_utc, now_et)
            if not result.changed_specialists:
                continue
            if global_tool_data is None:
                global_tool_data = await asyncio.to_thread(_read_global_tool_data)
            # read_tool_result is blocking boto3 I/O; run the batch of reads for this symbol in
            # a worker thread so it doesn't block the event loop for the duration of up to ~26
            # sequential DynamoDB round-trips (spec: don't make this worse ahead of Task 25's
            # /healthz sharing this same process/loop).
            tool_data = await asyncio.to_thread(_read_symbol_tool_data, symbol, global_tool_data)
            await _graph.ainvoke({
                "symbol": symbol, "mcp_client": mcp_client,
                "is_new_symbol": result.is_new_symbol,
                "changed_specialists": result.changed_specialists,
                "tool_data": tool_data,
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
    seen: set[str] = await asyncio.to_thread(_seed_seen_symbols)
    # Final review Finding 2: a cold start's first tick (discovery + input-data-agent + full
    # pipeline for every "new" watchlist symbol) can run long, and /healthz would 503 for that
    # entire window if the only heartbeat came from inside the loop below (after the first tick
    # returns). This pre-loop call is purely additive -- it gives the process credit for having
    # started, while the per-tick call still catches a genuinely hung loop.
    record_heartbeat(datetime.now(timezone.utc))
    while True:
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(_ET)
        try:
            seen = await scheduler_tick(mcp_client, now_utc, now_et, seen)
        except Exception:
            logger.exception("scheduler tick failed; will retry next interval")
        record_heartbeat(now_utc)
        await asyncio.sleep(tick_interval_seconds)
