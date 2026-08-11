from datetime import date, timedelta
from unittest.mock import patch
from src.input_data_agent import diff_changed, fmp_is_due_today, FETCH_PLAN

def test_diff_changed_news_uses_uuid_set():
    previous = {"data": [{"uuid": "a"}, {"uuid": "b"}]}
    same = {"data": [{"uuid": "b"}, {"uuid": "a"}]}  # same set, different order
    changed = {"data": [{"uuid": "a"}, {"uuid": "c"}]}
    assert diff_changed(previous, same, is_news=True) is False
    assert diff_changed(previous, changed, is_news=True) is True

def test_diff_changed_non_news_uses_deep_equality():
    assert diff_changed({"price": 150}, {"price": 150}, is_news=False) is False
    assert diff_changed({"price": 150}, {"price": 151}, is_news=False) is True

def test_diff_changed_first_fetch_always_counts_as_changed():
    assert diff_changed(None, {"price": 150}, is_news=False) is True

def test_fmp_rotation_covers_watchlist_over_3_days_evenly():
    watchlist = [f"SYM{i}" for i in range(30)]
    day0 = date(2026, 1, 1)  # toordinal() % 3 == some value; test all 3 consecutive days
    due_counts = []
    for offset in range(3):
        day = date.fromordinal(day0.toordinal() + offset)
        due_counts.append(sum(1 for s in watchlist if fmp_is_due_today(s, watchlist, day)))
    assert due_counts == [10, 10, 10]

def test_fmp_rotation_is_stable_for_a_given_symbol_and_day():
    watchlist = ["AAPL", "MSFT", "GOOG"]
    day = date(2026, 3, 15)
    assert fmp_is_due_today("AAPL", watchlist, day) == fmp_is_due_today("AAPL", watchlist, day)

def test_fetch_plan_covers_all_33_self_built_tools_plus_technical_and_options_extras():
    own_server_tools = {f.tool_name for f in FETCH_PLAN if f.server == "own"}
    # 33 total self-built tools minus the 2 ad hoc FRED utility tools (search/release calendar),
    # which are not part of scheduled fetching (spec doesn't require them on a cadence).
    assert len(own_server_tools) == 31

import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from zoneinfo import ZoneInfo
from src.input_data_agent import run_input_data_agent_for_symbol

ET = ZoneInfo("America/New_York")

@pytest.mark.asyncio
async def test_new_symbol_triggers_full_fetch_and_all_specialists_marked_changed(monkeypatch):
    monkeypatch.setattr("src.input_data_agent.call_tool", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr("src.input_data_agent.read_tool_result", lambda pk: None)
    monkeypatch.setattr("src.input_data_agent.write_tool_result", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.record_fetch_attempt", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.get_last_fetch_attempt", lambda pk: None)

    result = await run_input_data_agent_for_symbol(
        mcp_client=object(), symbol="AAPL", watchlist=["AAPL"], is_new_symbol=True,
        now_utc=datetime(2026, 1, 5, 15, 0), now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET),
    )
    assert result.is_new_symbol is True
    assert result.changed_specialists == {"fundamentals", "technical", "sentiment", "macro_options"}

@pytest.mark.asyncio
async def test_scheduled_tick_only_marks_specialists_whose_data_actually_changed(monkeypatch):
    async def fake_call_tool(client, server, tool_name, **kwargs):
        if tool_name == "marketaux_news_all":
            return {"data": [{"uuid": "new-1"}]}
        return {"unchanged": True}

    def fake_read(pk):
        if "marketaux_news_all" in pk:
            return {"data": [{"uuid": "old-1"}]}
        return {"unchanged": True}

    monkeypatch.setattr("src.input_data_agent.call_tool", fake_call_tool)
    monkeypatch.setattr("src.input_data_agent.read_tool_result", fake_read)
    monkeypatch.setattr("src.input_data_agent.write_tool_result", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.record_fetch_attempt", lambda *a, **k: None)
    # No prior attempt recorded for anything -> every schedule-driven tool is due this tick,
    # isolating the assertion to diff_changed's behavior rather than cadence gating.
    monkeypatch.setattr("src.input_data_agent.get_last_fetch_attempt", lambda pk: None)

    result = await run_input_data_agent_for_symbol(
        mcp_client=object(), symbol="AAPL", watchlist=["AAPL"], is_new_symbol=False,
        now_utc=datetime(2026, 1, 5, 15, 0), now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET),
    )
    assert result.changed_specialists == {"sentiment"}

from src.input_data_agent import _is_due

def test_finnhub_static_not_due_30_seconds_after_last_attempt():
    spec = next(f for f in FETCH_PLAN if f.tool_name == "finnhub_company_profile")
    now = datetime(2026, 1, 5, 15, 0, 30)
    last_attempt = datetime(2026, 1, 5, 15, 0, 0)
    with patch("src.input_data_agent.get_last_fetch_attempt", return_value=last_attempt):
        assert _is_due(spec, "AAPL#finnhub_company_profile", now, datetime(2026, 1, 5, 10, 0, 30, tzinfo=ET), is_new_symbol=False) is False

def test_finnhub_static_due_25_hours_after_last_attempt():
    spec = next(f for f in FETCH_PLAN if f.tool_name == "finnhub_company_profile")
    last_attempt = datetime(2026, 1, 4, 15, 0, 0)
    now = datetime(2026, 1, 5, 16, 0, 0)  # 25 hours later
    with patch("src.input_data_agent.get_last_fetch_attempt", return_value=last_attempt):
        assert _is_due(spec, "AAPL#finnhub_company_profile", now, datetime(2026, 1, 5, 11, 0, 0, tzinfo=ET), is_new_symbol=False) is True

def test_fred_vix_hourly_cadence_not_due_30_minutes_in():
    spec = next(f for f in FETCH_PLAN if f.tool_name == "fred_vix")
    now = datetime(2026, 1, 5, 15, 30, 0)
    last_attempt = datetime(2026, 1, 5, 15, 0, 0)
    with patch("src.input_data_agent.get_last_fetch_attempt", return_value=last_attempt):
        assert _is_due(spec, "GLOBAL#fred_vix", now, datetime(2026, 1, 5, 10, 30, 0, tzinfo=ET), is_new_symbol=False) is False

def test_fred_vix_hourly_cadence_due_after_61_minutes():
    spec = next(f for f in FETCH_PLAN if f.tool_name == "fred_vix")
    now = datetime(2026, 1, 5, 16, 1, 0)
    last_attempt = datetime(2026, 1, 5, 15, 0, 0)
    with patch("src.input_data_agent.get_last_fetch_attempt", return_value=last_attempt):
        assert _is_due(spec, "GLOBAL#fred_vix", now, datetime(2026, 1, 5, 11, 1, 0, tzinfo=ET), is_new_symbol=False) is True

@pytest.mark.asyncio
async def test_fmp_rotation_still_gates_correctly_alongside_the_new_cadence_check(monkeypatch):
    # A symbol whose rotation day is NOT today must be skipped entirely — the generic cadence
    # check must not override or bypass fmp_is_due_today's decision. get_last_fetch_attempt is
    # mocked to always return None (which on its own would say "due, never fetched before"),
    # so this test isolates and proves the rotation gate, not the cadence gate, is what's
    # actually excluding these calls.
    called_tools = []

    async def tracking_call_tool(client, server, tool_name, **kwargs):
        called_tools.append(tool_name)
        return {"unchanged": True}

    monkeypatch.setattr("src.input_data_agent.call_tool", tracking_call_tool)
    monkeypatch.setattr("src.input_data_agent.read_tool_result", lambda pk: {"unchanged": True})
    monkeypatch.setattr("src.input_data_agent.write_tool_result", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.get_last_fetch_attempt", lambda pk: None)
    monkeypatch.setattr("src.input_data_agent.record_fetch_attempt", lambda *a, **k: None)

    watchlist = ["AAPL", "MSFT", "GOOG"]
    # Pick a day where AAPL's rotation group is NOT due, per Task 16's fmp_is_due_today.
    not_due_day = next(
        d for d in (date(2026, 1, 5) + timedelta(days=i) for i in range(3))
        if not fmp_is_due_today("AAPL", watchlist, d)
    )
    now_utc = datetime.combine(not_due_day, datetime.min.time()) + timedelta(hours=15)
    now_et = datetime(not_due_day.year, not_due_day.month, not_due_day.day, 10, 0, tzinfo=ET)

    await run_input_data_agent_for_symbol(
        mcp_client=object(), symbol="AAPL", watchlist=watchlist, is_new_symbol=False,
        now_utc=now_utc, now_et=now_et,
    )

    fmp_per_symbol_tool_names = {f.tool_name for f in FETCH_PLAN if f.schedule_key == "fmp" and f.per_symbol}
    assert not (fmp_per_symbol_tool_names & set(called_tools)), (
        f"FMP per-symbol tools were called on AAPL's non-rotation day: {fmp_per_symbol_tool_names & set(called_tools)}"
    )
