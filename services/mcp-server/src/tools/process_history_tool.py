from mcp.server.fastmcp import FastMCP
from datetime import datetime
from common.dynamo import query_process_history

def register_process_history_tool(app: FastMCP) -> None:
    @app.tool()
    async def query_process_history_tool(symbol: str, since: str | None = None) -> list[dict]:
        """Query the append-only process-history log for a symbol: every agent run, why it ran, and its status."""
        since_dt = datetime.fromisoformat(since) if since else None
        return query_process_history(symbol, since=since_dt)
