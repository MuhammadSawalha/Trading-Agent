import json
import os
import uuid
from datetime import datetime, timezone
from langchain_mcp_adapters.client import MultiServerMCPClient
from .rate_limit.circuit_breaker import CircuitBreaker

CIRCUIT_BREAKER_PROTECTED_SERVERS = {"tradingview", "stock_scanner"}

def build_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient({
        "own": {"url": os.environ["OWN_MCP_SERVER_URL"], "transport": "streamable_http"},
        # Both third-party servers are locally self-hosted via an mcp-proxy stdio-to-SSE bridge
        # (see docker-compose.yaml) since neither has a native HTTP mode of its own -- hence
        # "sse", not "streamable_http", to match what mcp-proxy actually exposes.
        "tradingview": {"url": os.environ["TRADINGVIEW_MCP_URL"], "transport": "sse"},
        "stock_scanner": {"url": os.environ["STOCK_SCANNER_MCP_URL"], "transport": "sse"},
    })

# Both third-party servers share ONE breaker instance (spec §7 — they depend on the same
# upstream TradingView infrastructure), so this lives at module scope, not per-server.
_tradingview_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300)

class CircuitOpenError(Exception):
    pass

async def call_tool(client: MultiServerMCPClient, server: str, tool_name: str, **kwargs) -> dict:
    now = datetime.now(timezone.utc)
    protected = server in CIRCUIT_BREAKER_PROTECTED_SERVERS
    if protected and not _tradingview_breaker.allow_call(now):
        raise CircuitOpenError(f"circuit open for shared TradingView dependency (server={server})")
    try:
        tools = await client.get_tools(server_name=server)
        tool = next(t for t in tools if t.name == tool_name)
        # Invoke via the ToolCall input shape rather than a plain dict: langchain_mcp_adapters
        # builds every tool with response_format="content_and_artifact", and BaseTool's
        # _format_output only wraps the result in a ToolMessage (preserving `artifact`, where
        # the MCP structuredContent lives) when tool_call_id is not None. Passing a plain dict
        # leaves tool_call_id None and silently discards the artifact.
        message = await tool.ainvoke(
            {"type": "tool_call", "name": tool_name, "args": kwargs, "id": str(uuid.uuid4())}
        )
        result = _extract_structured_result(message)
    except Exception:
        if protected:
            _tradingview_breaker.record_failure(now)
        raise
    if protected:
        _tradingview_breaker.record_success(now)
    return result

def _extract_structured_result(message) -> dict:
    """Pull the actual structured payload out of the ToolMessage returned by an MCP tool.

    Tools whose MCP definition carries an output schema populate CallToolResult.structuredContent,
    which the adapter surfaces as artifact["structured_content"]. Tools without one (e.g. a FastMCP
    tool annotated bare `-> dict`, like score_verdict) have no artifact at all — their payload is
    JSON-encoded inside a single text content block.
    """
    if message.artifact and "structured_content" in message.artifact:
        return message.artifact["structured_content"]
    content = message.content
    if isinstance(content, list) and len(content) == 1 and content[0].get("type") == "text":
        return json.loads(content[0]["text"])
    raise ValueError(f"unexpected MCP tool result shape from '{message.name}': {content!r}")
