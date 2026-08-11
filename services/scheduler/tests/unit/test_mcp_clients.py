import os
import pytest
import src.mcp_clients as mcp_clients
from src.mcp_clients import build_mcp_client, call_tool
from src.rate_limit.circuit_breaker import CircuitBreaker

def test_client_configures_all_three_servers(monkeypatch):
    monkeypatch.setenv("OWN_MCP_SERVER_URL", "http://mcp-server:8001/mcp")
    monkeypatch.setenv("TRADINGVIEW_MCP_URL", "http://tradingview-mcp:9001/mcp")
    monkeypatch.setenv("STOCK_SCANNER_MCP_URL", "http://stock-scanner-mcp:9002/mcp")
    client = build_mcp_client()
    assert set(client.connections.keys()) == {"own", "tradingview", "stock_scanner"}
    assert client.connections["own"]["url"] == "http://mcp-server:8001/mcp"

async def test_get_tools_failure_trips_breaker_for_protected_server(monkeypatch):
    # A fresh, isolated breaker (threshold=1) swapped in for the module-level
    # singleton so this test doesn't share state with other tests and a single
    # failure is enough to observe the trip via the public `.state` property.
    fresh_breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=300)
    monkeypatch.setattr(mcp_clients, "_tradingview_breaker", fresh_breaker)

    class UnreachableServerClient:
        async def get_tools(self, *, server_name):
            # Simulates the network call to the tradingview/stock_scanner MCP
            # server failing before any tool list is ever obtained.
            raise ConnectionError("upstream unreachable")

    assert fresh_breaker.state == "closed"

    with pytest.raises(ConnectionError):
        await call_tool(UnreachableServerClient(), "tradingview", "some_tool")

    assert fresh_breaker.state == "open"
