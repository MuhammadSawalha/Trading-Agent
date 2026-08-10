from mcp.server.fastmcp import FastMCP
from ..clients.finnhub_client import finnhub_client

def register_finnhub_tools(app: FastMCP) -> None:
    client = finnhub_client()

    @app.tool()
    async def finnhub_company_profile(symbol: str) -> dict:
        """Company profile (name, industry, market cap, IPO date) for a stock symbol."""
        return await client.get("/stock/profile2", {"symbol": symbol})

    @app.tool()
    async def finnhub_peers(symbol: str) -> dict:
        """Peer companies in the same industry for a stock symbol."""
        return await client.get("/stock/peers", {"symbol": symbol})

    @app.tool()
    async def finnhub_basic_financials(symbol: str) -> dict:
        """Basic financial metrics (margins, ratios, per-share figures) for a stock symbol."""
        return await client.get("/stock/metric", {"symbol": symbol, "metric": "all"})

    @app.tool()
    async def finnhub_earnings_calendar(symbol: str) -> dict:
        """Upcoming and past earnings report dates for a stock symbol."""
        return await client.get("/calendar/earnings", {"symbol": symbol})

    @app.tool()
    async def finnhub_earnings_surprises(symbol: str) -> dict:
        """Historical EPS actual-vs-estimate surprises for a stock symbol."""
        return await client.get("/stock/earnings", {"symbol": symbol})

    @app.tool()
    async def finnhub_insider_transactions(symbol: str) -> dict:
        """Recent insider buy/sell transactions for a stock symbol."""
        return await client.get("/stock/insider-transactions", {"symbol": symbol})

    @app.tool()
    async def finnhub_insider_sentiment(symbol: str) -> dict:
        """Aggregate monthly insider sentiment (MSPR) for a stock symbol."""
        return await client.get("/stock/insider-sentiment", {"symbol": symbol})

    @app.tool()
    async def finnhub_lobbying_data(symbol: str) -> dict:
        """Corporate lobbying spend disclosures for a stock symbol."""
        return await client.get("/stock/lobbying", {"symbol": symbol})

    @app.tool()
    async def finnhub_usa_spending(symbol: str) -> dict:
        """US government contract spending records for a stock symbol."""
        return await client.get("/stock/usa-spending", {"symbol": symbol})

    @app.tool()
    async def finnhub_company_news(symbol: str, from_date: str, to_date: str) -> dict:
        """Company news articles for a stock symbol within a date range (YYYY-MM-DD)."""
        return await client.get("/company-news", {"symbol": symbol, "from": from_date, "to": to_date})

    @app.tool()
    async def finnhub_quote(symbol: str) -> dict:
        """Real-time quote: current price, change, high/low/open, previous close."""
        return await client.get("/quote", {"symbol": symbol})
