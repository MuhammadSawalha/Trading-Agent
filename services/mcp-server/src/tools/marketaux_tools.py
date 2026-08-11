from mcp.server.fastmcp import FastMCP
from ..clients.marketaux_client import marketaux_client


def register_marketaux_tools(app: FastMCP) -> None:
    client = marketaux_client()

    @app.tool()
    async def marketaux_news_all(symbols: str) -> dict:
        """Latest news articles (per-article sentiment, entity-tagged) for comma-separated stock symbols."""
        return await client.get("/news/all", {"symbols": symbols})
