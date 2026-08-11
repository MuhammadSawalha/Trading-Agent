from mcp.server.fastmcp import FastMCP
from ..clients.fmp_client import fmp_client

def register_fmp_tools(app: FastMCP) -> None:
    client = fmp_client()

    @app.tool()
    async def fmp_income_statement(symbol: str) -> dict:
        """Annual income statement (revenue, expenses, net income) for a stock symbol."""
        return await client.get("/income-statement", {"symbol": symbol})

    @app.tool()
    async def fmp_balance_sheet_statement(symbol: str) -> dict:
        """Annual balance sheet (assets, liabilities, equity) for a stock symbol."""
        return await client.get("/balance-sheet-statement", {"symbol": symbol})

    @app.tool()
    async def fmp_cash_flow_statement(symbol: str) -> dict:
        """Annual cash flow statement for a stock symbol."""
        return await client.get("/cash-flow-statement", {"symbol": symbol})

    @app.tool()
    async def fmp_financial_ratios(symbol: str) -> dict:
        """Key financial ratios (P/E, ROE, debt/equity, etc.) for a stock symbol."""
        return await client.get("/ratios", {"symbol": symbol})

    @app.tool()
    async def fmp_key_metrics(symbol: str) -> dict:
        """Per-share and valuation key metrics for a stock symbol."""
        return await client.get("/key-metrics", {"symbol": symbol})

    @app.tool()
    async def fmp_dcf_valuation(symbol: str) -> dict:
        """Discounted cash flow fair-value estimate for a stock symbol."""
        return await client.get("/discounted-cash-flow", {"symbol": symbol})

    @app.tool()
    async def fmp_ratings_snapshot(symbol: str) -> dict:
        """Current analyst rating snapshot (buy/hold/sell composite) for a stock symbol."""
        return await client.get("/ratings-snapshot", {"symbol": symbol})

    @app.tool()
    async def fmp_dividends_calendar(from_date: str, to_date: str) -> dict:
        """Dividend calendar across all companies within a date range (YYYY-MM-DD). Global, not per-symbol."""
        return await client.get("/dividends-calendar", {"from": from_date, "to": to_date})

    @app.tool()
    async def fmp_stock_splits_calendar(from_date: str, to_date: str) -> dict:
        """Stock split calendar across all companies within a date range (YYYY-MM-DD). Global, not per-symbol."""
        return await client.get("/splits-calendar", {"from": from_date, "to": to_date})

    @app.tool()
    async def fmp_economic_indicators(indicator_name: str) -> dict:
        """Named macroeconomic indicator series (e.g. GDP, CPI) from FMP's economic indicators dataset."""
        return await client.get("/economic-indicators", {"name": indicator_name})
