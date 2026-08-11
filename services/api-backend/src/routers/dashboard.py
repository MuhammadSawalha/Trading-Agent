from fastapi import APIRouter
from common.dynamo import read_tool_result, read_agent_output, query_process_history, read_watchlist

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
        history = query_process_history(symbol)
        last_updated = history[-1]["timestamp"] if history else None
        rows.append({"symbol": symbol, "verdict": verdict, "last_updated": last_updated})
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
