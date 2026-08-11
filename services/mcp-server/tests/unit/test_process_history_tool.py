import pytest
import boto3
from moto import mock_aws
from mcp.server.fastmcp import FastMCP
from datetime import datetime, timezone
from src.tools.process_history_tool import register_process_history_tool
from common.dynamo import append_process_history, ensure_tables_for_test

@pytest.mark.asyncio
async def test_process_history_tool_returns_entries_for_symbol():
    with mock_aws():
        ensure_tables_for_test()
        append_process_history("AAPL", "Sentiment", reason="news_cascade", status="finished",
                                timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
        app = FastMCP("test")
        register_process_history_tool(app)
        result = await app.call_tool("query_process_history_tool", {"symbol": "AAPL"})
        assert result  # non-empty
