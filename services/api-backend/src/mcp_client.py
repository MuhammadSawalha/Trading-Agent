import json
import os
import uuid
from langchain_mcp_adapters.client import MultiServerMCPClient

def build_own_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient({
        "own": {"url": os.environ["OWN_MCP_SERVER_URL"], "transport": "streamable_http"},
    })

async def call_own_tool(client: MultiServerMCPClient, tool_name: str, **kwargs) -> dict:
    tools = await client.get_tools(server_name="own")
    tool = next(t for t in tools if t.name == tool_name)
    # Invoke via the ToolCall input shape rather than a plain dict: langchain_mcp_adapters
    # builds every tool with response_format="content_and_artifact", and BaseTool's
    # _format_output only wraps the result in a ToolMessage (preserving `artifact`, where
    # the MCP structuredContent lives) when tool_call_id is not None. Passing a plain dict
    # leaves tool_call_id None and silently discards the artifact.
    message = await tool.ainvoke(
        {"type": "tool_call", "name": tool_name, "args": kwargs, "id": str(uuid.uuid4())}
    )
    return _extract_structured_result(message)

def _extract_structured_result(message) -> dict:
    """Pull the actual structured payload out of the ToolMessage returned by an MCP tool.

    Tools whose MCP definition carries an output schema populate CallToolResult.structuredContent,
    which the adapter surfaces as artifact["structured_content"]. Tools without one (e.g. a FastMCP
    tool annotated bare `-> dict`, like finnhub_company_profile) have no artifact at all — their
    payload is JSON-encoded inside a single text content block.
    """
    if message.artifact and "structured_content" in message.artifact:
        return message.artifact["structured_content"]
    content = message.content
    if isinstance(content, list) and len(content) == 1 and content[0].get("type") == "text":
        return json.loads(content[0]["text"])
    raise ValueError(f"unexpected MCP tool result shape from '{message.name}': {content!r}")
