import json

import pytest
import respx
import httpx
from mcp.server.fastmcp import FastMCP
from src.tools.finnhub_tools import register_finnhub_tools


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")


@pytest.fixture
def app():
    """A real FastMCP app with the finnhub tools registered against it.

    register_finnhub_tools() only defines the decorated tool functions --
    it makes no HTTP calls -- so no respx mocking is needed just to build
    this fixture.
    """
    app = FastMCP("test")
    register_finnhub_tools(app)
    return app


# (tool_name, endpoint_path, call_args, expected_query_params, mock_json_body)
TOOL_CASES = [
    (
        "finnhub_company_profile",
        "/stock/profile2",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"name": "Apple Inc.", "marketCapitalization": 3000000},
    ),
    (
        "finnhub_peers",
        "/stock/peers",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"peers": ["MSFT", "GOOGL"]},
    ),
    (
        "finnhub_basic_financials",
        "/stock/metric",
        {"symbol": "AAPL"},
        {"symbol": "AAPL", "metric": "all"},
        {"metric": {"currentRatio": 1.5}},
    ),
    (
        "finnhub_earnings_calendar",
        "/calendar/earnings",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"earningsCalendar": []},
    ),
    (
        "finnhub_earnings_surprises",
        "/stock/earnings",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"earnings": []},
    ),
    (
        "finnhub_insider_transactions",
        "/stock/insider-transactions",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"data": []},
    ),
    (
        "finnhub_insider_sentiment",
        "/stock/insider-sentiment",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"data": []},
    ),
    (
        "finnhub_lobbying_data",
        "/stock/lobbying",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"data": []},
    ),
    (
        "finnhub_usa_spending",
        "/stock/usa-spending",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"data": []},
    ),
    (
        "finnhub_company_news",
        "/company-news",
        {"symbol": "AAPL", "from_date": "2026-01-01", "to_date": "2026-01-08"},
        {"symbol": "AAPL", "from": "2026-01-01", "to": "2026-01-08"},
        {"news": []},
    ),
    (
        "finnhub_quote",
        "/quote",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"c": 150.0},
    ),
]

TOOL_NAMES = [case[0] for case in TOOL_CASES]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "tool_name, endpoint_path, call_args, expected_params, mock_body", TOOL_CASES, ids=TOOL_NAMES
)
async def test_finnhub_tool_calls_correct_endpoint(
    app, tool_name, endpoint_path, call_args, expected_params, mock_body
):
    """Each tool, invoked through the real call_tool() path, must hit the
    right Finnhub endpoint with the right query params and hand back the
    provider's JSON payload -- exercising the actual tool body, not just
    the underlying ProviderClient.get()."""
    route = respx.get(f"https://finnhub.io/api/v1{endpoint_path}").mock(
        return_value=httpx.Response(200, json=mock_body)
    )

    result = await app.call_tool(tool_name, call_args)

    assert route.called
    request_params = dict(route.calls.last.request.url.params)
    for key, value in expected_params.items():
        assert request_params[key] == value

    # call_tool(convert_result=True) on a bare `dict`-annotated tool (no
    # output schema) returns Sequence[ContentBlock]; for a dict-shaped
    # return value that collapses to a single TextContent block whose
    # .text is the JSON-serialized payload.
    assert len(result) == 1
    assert json.loads(result[0].text) == mock_body


@pytest.mark.asyncio
async def test_finnhub_tools_registration(app):
    """Verify that register_finnhub_tools registers all 11 expected tools."""
    tools = await app.list_tools()
    tool_names = {tool.name for tool in tools}

    assert tool_names == set(TOOL_NAMES)
