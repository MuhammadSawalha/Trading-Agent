import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from src.discovery import fetch_discovery_dashboards, DISCOVERY_TOOLS, _nasdaq_only

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
    # No prior discovery fetch recorded -- first call should always proceed regardless of cadence.
    monkeypatch.setattr("src.discovery.get_last_fetch_attempt", lambda pk: None)
    recorded = {}
    monkeypatch.setattr("src.discovery.record_fetch_attempt", lambda pk, ts: recorded.update({pk: ts}))

    await fetch_discovery_dashboards(mcp_client=object(), now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET))
    assert len(calls) == len(DISCOVERY_TOOLS) == 4
    assert "DASHBOARD#top_gainers" in written
    assert "DISCOVERY#LAST_FETCH" in recorded

@pytest.mark.asyncio
async def test_all_four_dashboards_request_nasdaq_not_a_broader_default(monkeypatch):
    # top_gainers/top_losers default to a crypto exchange (KUCOIN) when no `exchange` kwarg is
    # given, and top_volume/volume_breakout default to all major US exchanges combined --
    # without an explicit override the "discovery" dashboards would silently fill with crypto
    # pairs or non-NASDAQ tickers instead of the NASDAQ-only movers this app's watchlist deals in.
    calls = []

    async def fake_call_tool(client, server, tool_name, **kwargs):
        calls.append((tool_name, kwargs))
        return {"results": []}

    monkeypatch.setattr("src.discovery.call_tool", fake_call_tool)
    monkeypatch.setattr("src.discovery.write_tool_result", lambda *a, **k: None)
    monkeypatch.setattr("src.discovery.get_last_fetch_attempt", lambda pk: None)
    monkeypatch.setattr("src.discovery.record_fetch_attempt", lambda pk, ts: None)

    await fetch_discovery_dashboards(mcp_client=object(), now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET))

    calls_by_tool = dict(calls)
    assert calls_by_tool["top_gainers"].get("exchange") == "NASDAQ"
    assert calls_by_tool["top_losers"].get("exchange") == "NASDAQ"
    assert calls_by_tool["tradingview_top_volume"].get("exchange") == "NASDAQ"
    assert calls_by_tool["tradingview_volume_breakout"].get("exchange") == "NASDAQ"

def test_nasdaq_only_drops_non_nasdaq_rows_from_a_bare_list():
    # stock_scanner's tradingview_top_volume/tradingview_volume_breakout ignore the `exchange`
    # kwarg entirely (live-verified: identical NYSE-inclusive results with and without it), so
    # this client-side filter is the actual enforcement for those two dashboards.
    rows = [
        {"symbol": "NYSE:NU", "data": {}},
        {"symbol": "NASDAQ:CAPR", "data": {}},
        {"symbol": "OTC:TPSRF", "data": {}},
        {"symbol": "NASDAQ:NVDA", "data": {}},
    ]
    assert _nasdaq_only(rows) == [{"symbol": "NASDAQ:CAPR", "data": {}}, {"symbol": "NASDAQ:NVDA", "data": {}}]

def test_nasdaq_only_passes_through_non_list_results_unchanged():
    # top_gainers/top_losers (server="tradingview") come back as {"result": [...]}, already
    # genuinely NASDAQ-only via that server's own working exchange filter -- nothing to filter.
    wrapped = {"result": [{"symbol": "NASDAQ:BANL"}]}
    assert _nasdaq_only(wrapped) is wrapped

@pytest.mark.asyncio
async def test_fetch_discovery_dashboards_filters_stock_scanner_results_to_nasdaq(monkeypatch):
    async def fake_call_tool(client, server, tool_name, **kwargs):
        if server == "stock_scanner":
            return [{"symbol": "NYSE:NU"}, {"symbol": "NASDAQ:CAPR"}]
        return {"result": [{"symbol": "NASDAQ:BANL"}]}

    written = {}
    monkeypatch.setattr("src.discovery.call_tool", fake_call_tool)
    monkeypatch.setattr("src.discovery.write_tool_result", lambda pk, payload, ttl_seconds: written.update({pk: payload}))
    monkeypatch.setattr("src.discovery.get_last_fetch_attempt", lambda pk: None)
    monkeypatch.setattr("src.discovery.record_fetch_attempt", lambda pk, ts: None)

    await fetch_discovery_dashboards(mcp_client=object(), now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET))

    assert written["DASHBOARD#top_volume"] == [{"symbol": "NASDAQ:CAPR"}]
    assert written["DASHBOARD#volume_breakout"] == [{"symbol": "NASDAQ:CAPR"}]

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

@pytest.mark.asyncio
async def test_skips_fetch_when_called_again_within_cadence(monkeypatch):
    # Finding 2: fetch_discovery_dashboards must not re-fetch every ~60s (tick interval) --
    # it should honor the 30-min discovery-tier cadence (SCHEDULES["discovery"]).
    called = False

    async def fake_call_tool(*a, **k):
        nonlocal called
        called = True
        return {}

    now_et = datetime(2026, 1, 5, 10, 0, tzinfo=ET)
    last_attempt = now_et - timedelta(minutes=5)  # well within the 30-min cadence

    monkeypatch.setattr("src.discovery.call_tool", fake_call_tool)
    monkeypatch.setattr("src.discovery.write_tool_result", lambda *a, **k: None)
    monkeypatch.setattr("src.discovery.get_last_fetch_attempt", lambda pk: last_attempt)
    monkeypatch.setattr("src.discovery.record_fetch_attempt", lambda pk, ts: None)

    await fetch_discovery_dashboards(mcp_client=object(), now_et=now_et)
    assert called is False

@pytest.mark.asyncio
async def test_fetches_again_once_cadence_has_elapsed(monkeypatch):
    calls = []

    async def fake_call_tool(client, server, tool_name, **kwargs):
        calls.append((server, tool_name))
        return {"results": []}

    now_et = datetime(2026, 1, 5, 10, 0, tzinfo=ET)
    last_attempt = now_et - timedelta(minutes=31)  # just past the 30-min cadence

    written = {}
    recorded = {}
    monkeypatch.setattr("src.discovery.call_tool", fake_call_tool)
    monkeypatch.setattr("src.discovery.write_tool_result", lambda pk, payload, ttl_seconds: written.update({pk: payload}))
    monkeypatch.setattr("src.discovery.get_last_fetch_attempt", lambda pk: last_attempt)
    monkeypatch.setattr("src.discovery.record_fetch_attempt", lambda pk, ts: recorded.update({pk: ts}))

    await fetch_discovery_dashboards(mcp_client=object(), now_et=now_et)
    assert len(calls) == len(DISCOVERY_TOOLS) == 4
    assert "DISCOVERY#LAST_FETCH" in recorded
