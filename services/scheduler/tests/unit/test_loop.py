import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo
from src.loop import scheduler_tick
from src.input_data_agent import InputDataAgentResult

ET = ZoneInfo("America/New_York")

@pytest.mark.asyncio
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_new_symbol_triggers_a_graph_run(mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery):
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists={"fundamentals"}, is_new_symbol=True)
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock(return_value={})

    seen = await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen=set(),
    )
    assert seen == {"AAPL"}
    mock_graph.ainvoke.assert_awaited_once()

@pytest.mark.asyncio
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_no_change_skips_graph_run(mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery):
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists=set(), is_new_symbol=False)
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock()

    await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen={"AAPL"},
    )
    mock_graph.ainvoke.assert_not_awaited()
