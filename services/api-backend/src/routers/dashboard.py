from fastapi import APIRouter
from common.dynamo import read_tool_result, read_agent_output, query_process_history, read_watchlist, get_latest_process_history_entry

router = APIRouter(tags=["dashboard"])
_AGENT_NAMES = ["Fundamentals", "Technical", "Sentiment", "Macro_Options", "Bull", "Bear", "Risk", "Manager"]

@router.get("/dashboards/discovery")
async def discovery_dashboards():
    return {
        name: (read_tool_result(f"DASHBOARD#{name}") or {"results": []})
        for name in ["top_gainers", "top_losers", "top_volume", "volume_breakout"]
    }

@router.get("/dashboards/watchlist")
async def watchlist_dashboard():
    rows = []
    for symbol in read_watchlist():
        verdict = read_agent_output(symbol, "Manager") or {}
        latest = get_latest_process_history_entry(symbol)
        last_updated = latest["timestamp"] if latest else None
        # Spec 8.1 requires price and % change on every row. The scheduler
        # caches Finnhub's real-time quote per symbol; `c` is the current price
        # and `dp` the percent change. A symbol whose quote is not cached yet
        # (or is missing those keys) reports None rather than failing the
        # whole dashboard.
        quote = read_tool_result(f"{symbol}#finnhub_quote") or {}
        rows.append({
            "symbol": symbol,
            "price": quote.get("c"),
            "percent_change": quote.get("dp"),
            "verdict": verdict,
            "last_updated": last_updated,
        })
    return rows

@router.get("/symbols/{symbol}/detail")
async def symbol_detail(symbol: str):
    history = query_process_history(symbol)
    last_updated_by_agent = {}
    for entry in history:
        last_updated_by_agent[entry["agent"]] = entry["timestamp"]

    agents = {}
    for agent_name in _AGENT_NAMES:
        output = read_agent_output(symbol, agent_name) or {}
        key = agent_name.lower()
        agents[key] = {**output, "last_updated": last_updated_by_agent.get(agent_name)}
        agents[agent_name] = agents[key]  # also keyed by display name for the freshness-coloring UI

    return {"symbol": symbol, "agents": agents, "verdict": agents.get("manager", {})}
