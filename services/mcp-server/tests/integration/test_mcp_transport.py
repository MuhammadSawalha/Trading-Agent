import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session
from src.server import create_app

EXPECTED_TOOL_COUNT = 35

@pytest.mark.asyncio
async def test_all_35_tools_are_discoverable_over_real_transport(monkeypatch):
    for var in ["FINNHUB_API_KEY", "FMP_API_KEY", "FRED_API_KEY", "MARKETAUX_API_KEY"]:
        monkeypatch.setenv(var, "test-key")
    app = create_app()
    async with create_connected_server_and_client_session(app._mcp_server) as client:
        tools = await client.list_tools()
        assert len(tools.tools) == EXPECTED_TOOL_COUNT

@pytest.mark.asyncio
async def test_quote_tool_is_callable_over_real_transport(monkeypatch, respx_mock):
    import httpx
    for var in ["FINNHUB_API_KEY", "FMP_API_KEY", "FRED_API_KEY", "MARKETAUX_API_KEY"]:
        monkeypatch.setenv(var, "test-key")
    respx_mock.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 150.0})
    )
    app = create_app()
    async with create_connected_server_and_client_session(app._mcp_server) as client:
        result = await client.call_tool("finnhub_quote", {"symbol": "AAPL"})
        assert not result.isError
