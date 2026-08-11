import os
from datetime import datetime, timezone
from langchain_mcp_adapters.client import MultiServerMCPClient
from .rate_limit.circuit_breaker import CircuitBreaker

CIRCUIT_BREAKER_PROTECTED_SERVERS = {"tradingview", "stock_scanner"}

def build_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient({
        "own": {"url": os.environ["OWN_MCP_SERVER_URL"], "transport": "streamable_http"},
        "tradingview": {"url": os.environ["TRADINGVIEW_MCP_URL"], "transport": "streamable_http"},
        "stock_scanner": {"url": os.environ["STOCK_SCANNER_MCP_URL"], "transport": "streamable_http"},
    })

# Both third-party servers share ONE breaker instance (spec §7 — they depend on the same
# upstream TradingView infrastructure), so this lives at module scope, not per-server.
_tradingview_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300)

class CircuitOpenError(Exception):
    pass

async def call_tool(client: MultiServerMCPClient, server: str, tool_name: str, **kwargs) -> dict:
    now = datetime.now(timezone.utc)
    protected = server in CIRCUIT_BREAKER_PROTECTED_SERVERS
    if protected and not _tradingview_breaker.allow_call(now):
        raise CircuitOpenError(f"circuit open for shared TradingView dependency (server={server})")
    tools = await client.get_tools(server_name=server)
    tool = next(t for t in tools if t.name == tool_name)
    try:
        result = await tool.ainvoke(kwargs)
    except Exception:
        if protected:
            _tradingview_breaker.record_failure(now)
        raise
    if protected:
        _tradingview_breaker.record_success(now)
    return result
