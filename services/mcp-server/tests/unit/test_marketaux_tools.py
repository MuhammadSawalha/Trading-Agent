import json

import pytest
import respx
import httpx
from mcp.server.fastmcp import FastMCP
from src.tools.marketaux_tools import register_marketaux_tools


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("MARKETAUX_API_KEY", "test-key")


@pytest.fixture
def app():
    """A real FastMCP app with the marketaux tools registered against it.

    register_marketaux_tools() only defines the tool functions -- it makes no
    HTTP calls -- so no respx mocking is needed just to build this fixture.
    """
    app = FastMCP("test")
    register_marketaux_tools(app)
    return app


@pytest.mark.asyncio
@respx.mock
async def test_marketaux_news_all_calls_correct_endpoint(app):
    """The marketaux_news_all tool, invoked through the real call_tool() path,
    must hit the /news/all endpoint with the right symbols query param and
    hand back the provider's JSON payload with the uuid field intact."""
    mock_body = {
        "data": [
            {
                "uuid": "abc-123-def-456",
                "title": "Test Article",
                "sentiment": "positive",
            }
        ]
    }
    route = respx.get("https://api.marketaux.com/v1/news/all").mock(
        return_value=httpx.Response(200, json=mock_body)
    )

    result = await app.call_tool("marketaux_news_all", {"symbols": "AAPL"})

    assert route.called
    request_params = dict(route.calls.last.request.url.params)
    assert request_params["symbols"] == "AAPL"

    # call_tool(convert_result=True) on a bare `dict`-annotated tool (no
    # output schema) returns Sequence[ContentBlock]; for a dict-shaped
    # return value that collapses to a single TextContent block whose
    # .text is the JSON-serialized payload.
    assert len(result) == 1
    parsed_result = json.loads(result[0].text)
    assert parsed_result == mock_body

    # Explicitly verify the uuid field survives the round-trip
    assert parsed_result["data"][0]["uuid"] == "abc-123-def-456"


@pytest.mark.asyncio
async def test_marketaux_tools_registration(app):
    """Verify that register_marketaux_tools registers the marketaux_news_all tool."""
    tools = await app.list_tools()
    tool_names = {tool.name for tool in tools}

    assert "marketaux_news_all" in tool_names
