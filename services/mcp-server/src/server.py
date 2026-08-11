import logging

from mcp.server.fastmcp import FastMCP


def create_app() -> FastMCP:
    app = FastMCP("stock-research-mcp-server")

    # FastMCP's __init__ calls configure_logging(), which sets the root
    # logger to INFO. At that level httpx logs each outgoing request URL,
    # including the query string -- and ProviderClient.get() puts the
    # provider API key in the query string. Suppress httpx's own
    # request-logging so API keys never land in plaintext logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)

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
