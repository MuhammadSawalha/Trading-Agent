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
@respx.mock
async def test_marketaux_news_all_passes_language_filter(app):
    """When a language is supplied it must be forwarded as a query param, and
    when omitted it must not appear at all (rather than being sent as "None")."""
    route = respx.get("https://api.marketaux.com/v1/news/all").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    await app.call_tool("marketaux_news_all", {"symbols": "AAPL", "language": "en"})
    request_params = dict(route.calls.last.request.url.params)
    assert request_params["language"] == "en"

    await app.call_tool("marketaux_news_all", {"symbols": "AAPL"})
    request_params = dict(route.calls.last.request.url.params)
    assert "language" not in request_params


@pytest.mark.asyncio
@respx.mock
async def test_marketaux_news_all_paginates_and_merges_articles(app):
    # The provider's plan caps every single request at 3 articles regardless of `limit`, so
    # `pages` makes multiple requests and merges the results.
    route = respx.get("https://api.marketaux.com/v1/news/all").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"uuid": "a1", "title": "One"}, {"uuid": "a2", "title": "Two"}]}),
            httpx.Response(200, json={"data": [{"uuid": "a3", "title": "Three"}]}),
        ]
    )

    result = await app.call_tool("marketaux_news_all", {"symbols": "AAPL", "pages": 2})
    parsed = json.loads(result[0].text)

    assert [a["uuid"] for a in parsed["data"]] == ["a1", "a2", "a3"]
    assert route.call_count == 2
    assert dict(route.calls[0].request.url.params)["page"] == "1"
    assert dict(route.calls[1].request.url.params)["page"] == "2"


@pytest.mark.asyncio
@respx.mock
async def test_marketaux_news_all_dedupes_articles_repeated_across_pages(app):
    route = respx.get("https://api.marketaux.com/v1/news/all").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"uuid": "a1", "title": "One"}]}),
            httpx.Response(200, json={"data": [{"uuid": "a1", "title": "One"}]}),
        ]
    )

    result = await app.call_tool("marketaux_news_all", {"symbols": "AAPL", "pages": 2})
    parsed = json.loads(result[0].text)

    assert len(parsed["data"]) == 1
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_marketaux_news_all_stops_paginating_once_a_page_is_empty(app):
    route = respx.get("https://api.marketaux.com/v1/news/all").mock(
        side_effect=[
            httpx.Response(200, json={"data": []}),
            httpx.Response(200, json={"data": [{"uuid": "should-never-be-fetched"}]}),
        ]
    )

    result = await app.call_tool("marketaux_news_all", {"symbols": "AAPL", "pages": 3})
    parsed = json.loads(result[0].text)

    assert parsed["data"] == []
    assert route.call_count == 1  # the second, would-be-empty-triggering page is never requested


@pytest.mark.asyncio
async def test_marketaux_tools_registration(app):
    """Verify that register_marketaux_tools registers the marketaux_news_all tool."""
    tools = await app.list_tools()
    tool_names = {tool.name for tool in tools}

    assert "marketaux_news_all" in tool_names
