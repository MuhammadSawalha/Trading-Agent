import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from langchain_mcp_adapters.client import MultiServerMCPClient
from prometheus_client import Counter, Gauge
from .rate_limit.circuit_breaker import CircuitBreaker

CIRCUIT_BREAKER_PROTECTED_SERVERS = {"tradingview", "stock_scanner"}

# Task 55: feeds the CircuitBreakerOpen alert (monitoring/prometheus/rules/alerts.yaml),
# which matches on server=~"tradingview|stock_scanner". Numeric mapping matches the one
# documented on Task 57's Grafana panel: 0=closed, 1=open, 2=half_open.
_CIRCUIT_BREAKER_STATE_VALUES = {"closed": 0, "open": 1, "half_open": 2}

CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open) per protected MCP server",
    ["server"],
)

# Feeds the ToolCallTimeouts alert. Only incremented when a tool call is cut off by the
# asyncio.wait_for below -- record_failure/the circuit breaker still fire on ANY exception,
# unchanged; this is a narrower, additional signal, not a replacement.
MCP_TOOL_CALL_TIMEOUTS = Counter(
    "mcp_tool_call_timeouts_total",
    "Number of MCP tool calls that were cut off by the per-call timeout",
)

# The underlying transport (langchain_mcp_adapters over MCP's SSE client) has no per-call
# timeout tight enough to be useful here: the JSON-RPC session-level read timeout is never
# configured (stays None, i.e. no timeout), and the only naturally-raised httpx timeout is a
# 5-minute SSE-read-idle timeout -- far too coarse for a 60s scheduler tick and the
# "more than 5 timeouts in 10 minutes" alert threshold. Wrapping the call explicitly gives a
# distinguishable, tick-appropriate timeout signal instead.
_TOOL_CALL_TIMEOUT_SECONDS = 30.0

def _publish_circuit_breaker_state() -> None:
    """Both tradingview and stock_scanner share ONE CircuitBreaker instance (see
    _tradingview_breaker below), so mirror its single state onto both label values every
    time the shared breaker's state might have changed."""
    value = _CIRCUIT_BREAKER_STATE_VALUES[_tradingview_breaker.state]
    for server in CIRCUIT_BREAKER_PROTECTED_SERVERS:
        CIRCUIT_BREAKER_STATE.labels(server=server).set(value)

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
    if protected:
        allowed = _tradingview_breaker.allow_call(now)
        _publish_circuit_breaker_state()  # allow_call() can flip open -> half_open
        if not allowed:
            raise CircuitOpenError(f"circuit open for shared TradingView dependency (server={server})")
    try:
        tools = await client.get_tools(server_name=server)
        tool = next(t for t in tools if t.name == tool_name)
        # Invoke via the ToolCall input shape rather than a plain dict: langchain_mcp_adapters
        # builds every tool with response_format="content_and_artifact", and BaseTool's
        # _format_output only wraps the result in a ToolMessage (preserving `artifact`, where
        # the MCP structuredContent lives) when tool_call_id is not None. Passing a plain dict
        # leaves tool_call_id None and silently discards the artifact.
        message = await asyncio.wait_for(
            tool.ainvoke(
                {"type": "tool_call", "name": tool_name, "args": kwargs, "id": str(uuid.uuid4())}
            ),
            timeout=_TOOL_CALL_TIMEOUT_SECONDS,
        )
        result = _extract_structured_result(message)
    except asyncio.TimeoutError:
        MCP_TOOL_CALL_TIMEOUTS.inc()
        if protected:
            _tradingview_breaker.record_failure(now)
            _publish_circuit_breaker_state()
        raise
    except Exception:
        if protected:
            _tradingview_breaker.record_failure(now)
            _publish_circuit_breaker_state()
        raise
    if protected:
        _tradingview_breaker.record_success(now)
        _publish_circuit_breaker_state()
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
