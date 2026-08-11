from mcp.server.fastmcp import FastMCP


def create_app() -> FastMCP:
    # Binds to 0.0.0.0:8001 (rather than FastMCP's 127.0.0.1:8000 default) to
    # match the Dockerfile's EXPOSE 8001 and docker-compose's port mapping /
    # MCP_SERVER_URL, and to be reachable from sibling containers rather than
    # only from localhost inside this container.
    app = FastMCP("stock-research-mcp-server", host="0.0.0.0", port=8001)

    # httpx request-logging (which would log full URLs, including the
    # provider API key ProviderClient.get() puts in the query string) is
    # suppressed at import time in src/clients/base.py, which every provider
    # client (and therefore this app) imports.

    from .tools.finnhub_tools import register_finnhub_tools
    from .tools.fmp_tools import register_fmp_tools
    from .tools.fred_tools import register_fred_tools
    from .tools.marketaux_tools import register_marketaux_tools
    from .tools.scoring_tool import register_scoring_tool
    from .tools.process_history_tool import register_process_history_tool

    register_finnhub_tools(app)
    register_fmp_tools(app)
    register_fred_tools(app)
    register_marketaux_tools(app)
    register_scoring_tool(app)
    register_process_history_tool(app)

    return app


if __name__ == "__main__":
    create_app().run(transport="streamable-http")
