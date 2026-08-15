import asyncio
import json
import os
import pytest
from datetime import datetime, timedelta, timezone
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
    # The gauge mirrors the ONE shared breaker's state onto BOTH label values, even
    # though this failure only ever went through the "tradingview" server argument.
    assert mcp_clients.CIRCUIT_BREAKER_STATE.labels(server="tradingview")._value.get() == 1
    assert mcp_clients.CIRCUIT_BREAKER_STATE.labels(server="stock_scanner")._value.get() == 1

def test_circuit_breaker_gauge_reflects_closed_open_half_open_closed_cycle(monkeypatch):
    # Task 55: drives the shared breaker through a full closed -> open -> half_open ->
    # closed cycle and asserts the circuit_breaker_state gauge (0/1/2) tracks it for both
    # label values every step of the way -- not just at the two endpoints.
    fresh_breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
    monkeypatch.setattr(mcp_clients, "_tradingview_breaker", fresh_breaker)
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def assert_gauge_is(expected: int):
        for server in ("tradingview", "stock_scanner"):
            assert mcp_clients.CIRCUIT_BREAKER_STATE.labels(server=server)._value.get() == expected

    mcp_clients._publish_circuit_breaker_state()
    assert_gauge_is(0)  # closed

    fresh_breaker.record_failure(t0)  # threshold=1 -> opens immediately
    mcp_clients._publish_circuit_breaker_state()
    assert_gauge_is(1)  # open

    fresh_breaker.allow_call(t0 + timedelta(seconds=61))  # cooldown elapsed -> half_open probe
    mcp_clients._publish_circuit_breaker_state()
    assert_gauge_is(2)  # half_open

    fresh_breaker.record_success(t0 + timedelta(seconds=61))
    mcp_clients._publish_circuit_breaker_state()
    assert_gauge_is(0)  # closed again

async def test_timeout_increments_counter_and_trips_breaker_via_call_tool(monkeypatch):
    # Task 55: bounds a hung tool call with asyncio.wait_for -- verify the counter
    # increments on that specific TimeoutError path and that record_failure/the circuit
    # breaker still fire exactly as they do for any other exception (unchanged behavior).
    fresh_breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=300)
    monkeypatch.setattr(mcp_clients, "_tradingview_breaker", fresh_breaker)
    monkeypatch.setattr(mcp_clients, "_TOOL_CALL_TIMEOUT_SECONDS", 0.01)

    async def hang_forever(**kwargs):
        await asyncio.sleep(10)
        return ("unreachable", None)  # pragma: no cover

    slow_tool = StructuredTool.from_function(
        coroutine=hang_forever, name="slow_tool", description="hangs",
        response_format="content_and_artifact",
    )
    client = _client_serving(slow_tool)

    before = mcp_clients.MCP_TOOL_CALL_TIMEOUTS._value.get()

    with pytest.raises(asyncio.TimeoutError):
        await call_tool(client, "tradingview", "slow_tool")

    assert mcp_clients.MCP_TOOL_CALL_TIMEOUTS._value.get() == before + 1
    assert fresh_breaker.state == "open"
    assert mcp_clients.CIRCUIT_BREAKER_STATE.labels(server="tradingview")._value.get() == 1
    assert mcp_clients.CIRCUIT_BREAKER_STATE.labels(server="stock_scanner")._value.get() == 1

async def test_non_timeout_exception_does_not_increment_timeout_counter(monkeypatch):
    # A schema error, network error, etc. must trip the breaker (existing behavior,
    # unchanged) WITHOUT being miscounted as a timeout.
    fresh_breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=300)
    monkeypatch.setattr(mcp_clients, "_tradingview_breaker", fresh_breaker)

    async def raise_value_error(**kwargs):
        raise ValueError("not a timeout")

    failing_tool = StructuredTool.from_function(
        coroutine=raise_value_error, name="failing_tool", description="fails",
        response_format="content_and_artifact",
    )
    client = _client_serving(failing_tool)

    before = mcp_clients.MCP_TOOL_CALL_TIMEOUTS._value.get()

    with pytest.raises(ValueError):
        await call_tool(client, "tradingview", "failing_tool")

    assert mcp_clients.MCP_TOOL_CALL_TIMEOUTS._value.get() == before
    assert fresh_breaker.state == "open"

async def test_successful_protected_call_sets_gauge_closed(monkeypatch):
    fresh_breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=300)
    monkeypatch.setattr(mcp_clients, "_tradingview_breaker", fresh_breaker)
    fresh_breaker.record_failure(datetime.now(timezone.utc))
    mcp_clients._publish_circuit_breaker_state()
    assert mcp_clients.CIRCUIT_BREAKER_STATE.labels(server="tradingview")._value.get() == 1

    # Force straight back to closed to isolate what record_success's gauge update does,
    # independent of the half_open transition already covered above.
    fresh_breaker._state = "closed"
    fresh_breaker._opened_at = None

    payload = {"ok": True}
    tool = _fake_mcp_tool("some_tool", [{"type": "text", "text": json.dumps(payload)}], None)

    result = await call_tool(_client_serving(tool), "tradingview", "some_tool")

    assert result == payload
    assert mcp_clients.CIRCUIT_BREAKER_STATE.labels(server="tradingview")._value.get() == 0
    assert mcp_clients.CIRCUIT_BREAKER_STATE.labels(server="stock_scanner")._value.get() == 0

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
