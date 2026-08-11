import json
import os
import pytest
from unittest.mock import AsyncMock
from langchain_core.tools import StructuredTool
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

def _fake_mcp_tool(name: str, content, artifact):
    """A real StructuredTool built the way langchain_mcp_adapters builds MCP tools —
    response_format="content_and_artifact" — so call_tool's result extraction is
    exercised against genuine LangChain machinery rather than a mock."""
    def fn(**kwargs):
        """Fake MCP tool for testing call_tool's result extraction."""
        return (content, artifact)
    return StructuredTool.from_function(func=fn, name=name, response_format="content_and_artifact")

def _client_serving(tool):
    client = AsyncMock()
    client.get_tools = AsyncMock(return_value=[tool])
    return client

async def test_call_tool_returns_structured_content_from_artifact():
    # An MCP tool WITH an output schema: structuredContent arrives as the artifact,
    # which BaseTool discards entirely unless invoked with a ToolCall.
    payload = {"net_score": 42.0, "confidence": 60.0, "label": "Bullish, moderate confidence"}
    tool = _fake_mcp_tool(
        "score_verdict",
        [{"type": "text", "text": json.dumps(payload)}],
        {"structured_content": payload},
    )

    result = await call_tool(_client_serving(tool), "own", "score_verdict", risk_level="low")

    assert result == payload

async def test_call_tool_falls_back_to_json_text_when_tool_has_no_output_schema():
    # A FastMCP tool annotated bare `-> dict` generates outputSchema: None, so
    # CallToolResult.structuredContent — and therefore the artifact — is None, and
    # the payload is JSON-encoded inside a single text content block instead.
    payload = {"net_score": -12.5, "confidence": 30.0, "label": "Bearish, low confidence"}
    tool = _fake_mcp_tool(
        "score_verdict",
        [{"type": "text", "text": json.dumps(payload)}],
        None,
    )

    result = await call_tool(_client_serving(tool), "own", "score_verdict", risk_level="high")

    assert result == payload
