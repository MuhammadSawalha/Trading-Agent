from mcp.server.fastmcp import FastMCP
from ..clients.marketaux_client import marketaux_client


def register_marketaux_tools(app: FastMCP) -> None:
    client = marketaux_client()

    @app.tool()
    async def marketaux_news_all(symbols: str, language: str | None = None, pages: int = 1) -> dict:
        """Latest news articles (per-article sentiment, entity-tagged) for comma-separated stock
        symbols, optionally restricted to a comma-separated language list (e.g. "en").

        The plan behind MARKETAUX_API_KEY caps every request at 3 articles regardless of any
        `limit` param, so `pages` (each a separate request) is the only way to widen the pool
        -- callers that need more than 3 candidates before their own relevance filtering
        should request more pages, at the cost of `pages` calls against the daily quota
        instead of 1.
        """
        params = {"symbols": symbols}
        if language:
            params["language"] = language

        seen_uuids: set[str] = set()
        articles: list[dict] = []
        for page in range(1, pages + 1):
            result = await client.get("/news/all", {**params, "page": page})
            page_articles = result.get("data", [])
            if not page_articles:
                break
            for article in page_articles:
                uuid = article.get("uuid")
                if uuid is not None and uuid in seen_uuids:
                    continue
                if uuid is not None:
                    seen_uuids.add(uuid)
                articles.append(article)
        return {"data": articles}
