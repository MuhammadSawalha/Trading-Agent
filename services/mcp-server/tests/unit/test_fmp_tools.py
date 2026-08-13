import json

import pytest
import respx
import httpx
from mcp.server.fastmcp import FastMCP
from src.tools.fmp_tools import register_fmp_tools


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")


@pytest.fixture
def app():
    """A real FastMCP app with the fmp tools registered against it.

    register_fmp_tools() only defines the decorated tool functions --
    it makes no HTTP calls -- so no respx mocking is needed just to build
    this fixture.
    """
    app = FastMCP("test")
    register_fmp_tools(app)
    return app


# (tool_name, endpoint_path, call_args, expected_query_params, mock_json_body)
TOOL_CASES = [
    (
        # FMP's statement/ratio/metric endpoints return a bare JSON array (one entry per
        # fiscal period), not a single dict -- verified against the live API.
        "fmp_income_statement",
        "/income-statement",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        [{"revenue": 383285000000}],
    ),
    (
        "fmp_balance_sheet_statement",
        "/balance-sheet-statement",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        [{"totalAssets": 352755000000}],
    ),
    (
        "fmp_cash_flow_statement",
        "/cash-flow-statement",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        [{"operatingCashflow": 110543000000}],
    ),
    (
        "fmp_financial_ratios",
        "/ratios",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        [{"priceToEarningsRatio": 28.5}],
    ),
    (
        "fmp_key_metrics",
        "/key-metrics",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        [{"peRatio": 28.5, "marketCapitalization": 2800000000000}],
    ),
    (
        "fmp_dcf_valuation",
        "/discounted-cash-flow",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"dcfValue": 187.5},
    ),
    (
        "fmp_ratings_snapshot",
        "/ratings-snapshot",
        {"symbol": "AAPL"},
        {"symbol": "AAPL"},
        {"ratingScore": 4.7},
    ),
    (
        "fmp_dividends_calendar",
        "/dividends-calendar",
        {"from_date": "2026-01-01", "to_date": "2026-01-31"},
        {"from": "2026-01-01", "to": "2026-01-31"},
        {"data": []},
    ),
    (
        "fmp_stock_splits_calendar",
        "/splits-calendar",
        {"from_date": "2026-01-01", "to_date": "2026-01-31"},
        {"from": "2026-01-01", "to": "2026-01-31"},
        {"data": []},
    ),
    (
        "fmp_economic_indicators",
        "/economic-indicators",
        {"indicator_name": "GDP"},
        {"name": "GDP"},
        {"real_gdp": [150000000000]},
    ),
]

TOOL_NAMES = [case[0] for case in TOOL_CASES]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "tool_name, endpoint_path, call_args, expected_params, mock_body", TOOL_CASES, ids=TOOL_NAMES
)
async def test_fmp_tool_calls_correct_endpoint(
    app, tool_name, endpoint_path, call_args, expected_params, mock_body
):
    """Each tool, invoked through the real call_tool() path, must hit the
    right FMP endpoint with the right query params and hand back the
    provider's JSON payload -- exercising the actual tool body, not just
    the underlying ProviderClient.get()."""
    route = respx.get(f"https://financialmodelingprep.com/stable{endpoint_path}").mock(
        return_value=httpx.Response(200, json=mock_body)
    )

    result = await app.call_tool(tool_name, call_args)

    assert route.called
    request_params = dict(route.calls.last.request.url.params)
    for key, value in expected_params.items():
        assert request_params[key] == value

    if isinstance(mock_body, list):
        # A `list[dict]`-annotated tool (the statement/ratio/metric endpoints) has an output
        # schema, so call_tool(convert_result=True) returns (unstructured_content,
        # structured_content) -- FastMCP wraps a non-dict-with-str-keys return type as
        # {"result": ...} in the structured half.
        _, structured = result
        assert structured == {"result": mock_body}
    else:
        # A bare `dict`-annotated tool has no output schema, so call_tool returns
        # Sequence[ContentBlock]; a dict-shaped return value collapses to a single
        # TextContent block whose .text is the JSON-serialized payload.
        assert len(result) == 1
        assert json.loads(result[0].text) == mock_body


@pytest.mark.asyncio
async def test_fmp_tools_registration(app):
    """Verify that register_fmp_tools registers all 10 expected tools."""
    tools = await app.list_tools()
    tool_names = {tool.name for tool in tools}

    assert tool_names == set(TOOL_NAMES)
