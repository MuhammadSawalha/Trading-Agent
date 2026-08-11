import os
from src.mcp_clients import build_mcp_client

def test_client_configures_all_three_servers(monkeypatch):
    monkeypatch.setenv("OWN_MCP_SERVER_URL", "http://mcp-server:8001/mcp")
    monkeypatch.setenv("TRADINGVIEW_MCP_URL", "http://tradingview-mcp:9001/mcp")
    monkeypatch.setenv("STOCK_SCANNER_MCP_URL", "http://stock-scanner-mcp:9002/mcp")
    client = build_mcp_client()
    assert set(client.connections.keys()) == {"own", "tradingview", "stock_scanner"}
    assert client.connections["own"]["url"] == "http://mcp-server:8001/mcp"
