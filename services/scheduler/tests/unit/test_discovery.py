import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from zoneinfo import ZoneInfo
from src.discovery import fetch_discovery_dashboards, DISCOVERY_TOOLS

ET = ZoneInfo("America/New_York")

@pytest.mark.asyncio
async def test_fetches_all_four_dashboards_during_active_window(monkeypatch):
    calls = []

    async def fake_call_tool(client, server, tool_name, **kwargs):
        calls.append((server, tool_name))
        return {"results": []}

    written = {}
    monkeypatch.setattr("src.discovery.call_tool", fake_call_tool)
    monkeypatch.setattr("src.discovery.write_tool_result", lambda pk, payload, ttl_seconds: written.update({pk: payload}))

    await fetch_discovery_dashboards(mcp_client=object(), now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET))
    assert len(calls) == len(DISCOVERY_TOOLS) == 4
    assert "DASHBOARD#top_gainers" in written

@pytest.mark.asyncio
async def test_skips_fetch_when_paused_overnight(monkeypatch):
    called = False

    async def fake_call_tool(*a, **k):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("src.discovery.call_tool", fake_call_tool)
    monkeypatch.setattr("src.discovery.write_tool_result", lambda *a, **k: None)

    await fetch_discovery_dashboards(mcp_client=object(), now_et=datetime(2026, 1, 5, 22, 0, tzinfo=ET))
    assert called is False
