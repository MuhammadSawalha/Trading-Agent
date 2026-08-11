import pytest
import respx
import httpx
import os
from src.clients.finnhub_client import finnhub_client

@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_quote_calls_correct_endpoint_with_symbol():
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 150.0})
    )
    client = finnhub_client()
    result = await client.get("/quote", {"symbol": "AAPL"})
    assert result == {"c": 150.0}

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_company_news_passes_date_range():
    route = respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = finnhub_client()
    await client.get("/company-news", {"symbol": "AAPL", "from": "2026-01-01", "to": "2026-01-08"})
    assert route.calls.last.request.url.params["from"] == "2026-01-01"
    assert route.calls.last.request.url.params["to"] == "2026-01-08"

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_insider_sentiment_endpoint():
    respx.get("https://finnhub.io/api/v1/stock/insider-sentiment").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = finnhub_client()
    result = await client.get("/stock/insider-sentiment", {"symbol": "AAPL"})
    assert result == {"data": []}

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_company_profile_endpoint():
    route = respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": "Apple Inc.", "marketCapitalization": 3000000})
    )
    client = finnhub_client()
    result = await client.get("/stock/profile2", {"symbol": "AAPL"})
    assert result == {"name": "Apple Inc.", "marketCapitalization": 3000000}
    assert route.calls.last.request.url.params["symbol"] == "AAPL"

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_peers_endpoint():
    route = respx.get("https://finnhub.io/api/v1/stock/peers").mock(
        return_value=httpx.Response(200, json=["MSFT", "GOOGL"])
    )
    client = finnhub_client()
    result = await client.get("/stock/peers", {"symbol": "AAPL"})
    assert result == ["MSFT", "GOOGL"]
    assert route.calls.last.request.url.params["symbol"] == "AAPL"

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_basic_financials_endpoint():
    route = respx.get("https://finnhub.io/api/v1/stock/metric").mock(
        return_value=httpx.Response(200, json={"metric": {"currentRatio": 1.5}})
    )
    client = finnhub_client()
    result = await client.get("/stock/metric", {"symbol": "AAPL", "metric": "all"})
    assert result == {"metric": {"currentRatio": 1.5}}
    assert route.calls.last.request.url.params["symbol"] == "AAPL"
    assert route.calls.last.request.url.params["metric"] == "all"

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_earnings_calendar_endpoint():
    route = respx.get("https://finnhub.io/api/v1/calendar/earnings").mock(
        return_value=httpx.Response(200, json={"earningsCalendar": []})
    )
    client = finnhub_client()
    result = await client.get("/calendar/earnings", {"symbol": "AAPL"})
    assert result == {"earningsCalendar": []}
    assert route.calls.last.request.url.params["symbol"] == "AAPL"

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_earnings_surprises_endpoint():
    route = respx.get("https://finnhub.io/api/v1/stock/earnings").mock(
        return_value=httpx.Response(200, json={"earnings": []})
    )
    client = finnhub_client()
    result = await client.get("/stock/earnings", {"symbol": "AAPL"})
    assert result == {"earnings": []}
    assert route.calls.last.request.url.params["symbol"] == "AAPL"

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_insider_transactions_endpoint():
    route = respx.get("https://finnhub.io/api/v1/stock/insider-transactions").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = finnhub_client()
    result = await client.get("/stock/insider-transactions", {"symbol": "AAPL"})
    assert result == {"data": []}
    assert route.calls.last.request.url.params["symbol"] == "AAPL"

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_lobbying_data_endpoint():
    route = respx.get("https://finnhub.io/api/v1/stock/lobbying").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = finnhub_client()
    result = await client.get("/stock/lobbying", {"symbol": "AAPL"})
    assert result == {"data": []}
    assert route.calls.last.request.url.params["symbol"] == "AAPL"

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_usa_spending_endpoint():
    route = respx.get("https://finnhub.io/api/v1/stock/usa-spending").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = finnhub_client()
    result = await client.get("/stock/usa-spending", {"symbol": "AAPL"})
    assert result == {"data": []}
    assert route.calls.last.request.url.params["symbol"] == "AAPL"

@pytest.mark.asyncio
@respx.mock
async def test_finnhub_tools_registration():
    """Verify that register_finnhub_tools registers all 11 expected tools."""
    from mcp.server.fastmcp import FastMCP
    from src.tools.finnhub_tools import register_finnhub_tools

    # Mock all Finnhub endpoints to allow the client to initialize without network calls
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/stock/peers").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/stock/metric").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/calendar/earnings").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/stock/earnings").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/stock/insider-transactions").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/stock/insider-sentiment").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/stock/lobbying").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/stock/usa-spending").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json={})
    )

    app = FastMCP("test")
    register_finnhub_tools(app)

    tools = await app.list_tools()
    tool_names = {tool.name for tool in tools}

    expected_tools = {
        "finnhub_company_profile",
        "finnhub_peers",
        "finnhub_basic_financials",
        "finnhub_earnings_calendar",
        "finnhub_earnings_surprises",
        "finnhub_insider_transactions",
        "finnhub_insider_sentiment",
        "finnhub_lobbying_data",
        "finnhub_usa_spending",
        "finnhub_company_news",
        "finnhub_quote",
    }

    assert tool_names == expected_tools
