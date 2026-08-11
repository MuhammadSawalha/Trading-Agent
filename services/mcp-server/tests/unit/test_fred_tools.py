import json

import pytest
import respx
import httpx
from mcp.server.fastmcp import FastMCP
from src.tools.fred_tools import register_fred_tools


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")


@pytest.fixture
def app():
    """A real FastMCP app with the fred tools registered against it.

    register_fred_tools() only defines the tool functions -- it makes no
    HTTP calls -- so no respx mocking is needed just to build this fixture.
    """
    app = FastMCP("test")
    register_fred_tools(app)
    return app


# (tool_name, series_id) -- the nine parameter-identical series tools,
# each driven off the same fixed series ID mapping used by _SERIES_TOOLS
# in src/tools/fred_tools.py.
SERIES_TOOL_CASES = [
    ("fred_federal_funds_rate", "DFF"),
    ("fred_10y_treasury_yield", "DGS10"),
    ("fred_2y_treasury_yield", "DGS2"),
    ("fred_cpi", "CPIAUCSL"),
    ("fred_unemployment_rate", "UNRATE"),
    ("fred_nonfarm_payrolls", "PAYEMS"),
    ("fred_real_gdp", "GDPC1"),
    ("fred_vix", "VIXCLS"),
    ("fred_consumer_sentiment", "UMCSENT"),
]

SERIES_TOOL_NAMES = [case[0] for case in SERIES_TOOL_CASES]

ALL_TOOL_NAMES = SERIES_TOOL_NAMES + ["fred_series_search", "fred_release_calendar"]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("tool_name, series_id", SERIES_TOOL_CASES, ids=SERIES_TOOL_NAMES)
async def test_series_tool_calls_correct_endpoint(app, tool_name, series_id):
    """Each series tool, invoked through the real call_tool() path, must hit
    /series/observations with its own fixed series_id -- exercising the
    actual tool body, not just the underlying ProviderClient.get()."""
    mock_body = {"observations": [{"date": "2026-08-01", "value": "5.33"}]}
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=mock_body)
    )

    result = await app.call_tool(tool_name, {})

    assert route.called
    request_params = dict(route.calls.last.request.url.params)
    assert request_params["series_id"] == series_id
    assert request_params["file_type"] == "json"

    assert len(result) == 1
    assert json.loads(result[0].text) == mock_body


@pytest.mark.asyncio
@respx.mock
async def test_series_tool_passes_observation_date_range(app):
    """observation_start / observation_end, when supplied, must be forwarded
    as query params."""
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json={"observations": []})
    )

    await app.call_tool(
        "fred_federal_funds_rate",
        {"observation_start": "2026-01-01", "observation_end": "2026-06-30"},
    )

    request_params = dict(route.calls.last.request.url.params)
    assert request_params["observation_start"] == "2026-01-01"
    assert request_params["observation_end"] == "2026-06-30"


@pytest.mark.asyncio
@respx.mock
async def test_fred_series_search_calls_correct_endpoint(app):
    mock_body = {"seriess": [{"id": "UNRATE", "title": "Unemployment Rate"}]}
    route = respx.get("https://api.stlouisfed.org/fred/series/search").mock(
        return_value=httpx.Response(200, json=mock_body)
    )

    result = await app.call_tool("fred_series_search", {"search_text": "unemployment"})

    assert route.called
    request_params = dict(route.calls.last.request.url.params)
    assert request_params["search_text"] == "unemployment"
    assert request_params["file_type"] == "json"

    assert len(result) == 1
    assert json.loads(result[0].text) == mock_body


@pytest.mark.asyncio
@respx.mock
async def test_fred_release_calendar_calls_correct_endpoint(app):
    mock_body = {"release_dates": [{"release_id": 10, "date": "2026-08-15"}]}
    route = respx.get("https://api.stlouisfed.org/fred/releases/dates").mock(
        return_value=httpx.Response(200, json=mock_body)
    )

    result = await app.call_tool(
        "fred_release_calendar",
        {"realtime_start": "2026-08-01", "realtime_end": "2026-08-31"},
    )

    assert route.called
    request_params = dict(route.calls.last.request.url.params)
    assert request_params["realtime_start"] == "2026-08-01"
    assert request_params["realtime_end"] == "2026-08-31"
    assert request_params["file_type"] == "json"

    assert len(result) == 1
    assert json.loads(result[0].text) == mock_body


@pytest.mark.asyncio
async def test_fred_tools_registration(app):
    """Verify that register_fred_tools registers all 11 expected tools."""
    tools = await app.list_tools()
    tool_names = {tool.name for tool in tools}

    assert tool_names == set(ALL_TOOL_NAMES)
