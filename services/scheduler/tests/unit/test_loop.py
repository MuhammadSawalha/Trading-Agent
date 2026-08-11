import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo
import src.loop
from src.loop import scheduler_tick
from src.input_data_agent import InputDataAgentResult

ET = ZoneInfo("America/New_York")

@pytest.fixture(autouse=True)
def _reset_graph_singleton():
    # src.loop._graph is a module-level lazily-built singleton, cached across calls to
    # scheduler_tick. If left set from a previous test, `if _graph is None: _graph =
    # build_graph()` never re-fires, so a later test's own `build_graph` patch is never
    # invoked and its mock assertions become vacuous. Reset before and after every test.
    src.loop._graph = None
    yield
    src.loop._graph = None

@pytest.mark.asyncio
@patch("src.loop.read_tool_result")
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_new_symbol_triggers_a_graph_run(
    mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery, mock_read_tool_result
):
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists={"fundamentals"}, is_new_symbol=True)
    mock_read_tool_result.return_value = None
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock(return_value={})

    seen = await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen=set(),
    )
    assert seen == {"AAPL"}
    mock_graph.ainvoke.assert_awaited_once()

@pytest.mark.asyncio
@patch("src.loop.read_tool_result")
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_no_change_skips_graph_run(
    mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery, mock_read_tool_result
):
    # read_tool_result is mocked (rather than left to hit real DynamoDB) so that if the
    # skip-on-no-change guard were ever removed, _build_tool_data would succeed and the test
    # would fail on a real assertion -- not incidentally pass because an unrelated AWS call
    # raised and got swallowed by the per-symbol try/except.
    mock_read_tool_result.return_value = None
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists=set(), is_new_symbol=False)
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock()

    await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen={"AAPL"},
    )
    mock_graph.ainvoke.assert_not_awaited()

@pytest.mark.asyncio
@patch("src.loop.read_tool_result")
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_tool_data_is_populated_from_dynamo_for_changed_specialists(
    mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery, mock_read_tool_result
):
    # Finding 1: tool_data must be assembled from DynamoDB (via read_tool_result), keyed by
    # specialist name, not hardcoded to {} -- otherwise every specialist LLM call runs on an
    # empty dict regardless of what was actually fetched.
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists={"fundamentals"}, is_new_symbol=True)
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock(return_value={})

    known_payload = {"name": "Apple Inc."}

    def fake_read_tool_result(pk):
        if pk == "AAPL#finnhub_company_profile":
            return known_payload
        return None

    mock_read_tool_result.side_effect = fake_read_tool_result

    await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen=set(),
    )

    mock_graph.ainvoke.assert_awaited_once()
    invoked_state = mock_graph.ainvoke.call_args[0][0]
    assert invoked_state["tool_data"]["fundamentals"]["finnhub_company_profile"] == known_payload

@pytest.mark.asyncio
@patch("src.loop.read_tool_result")
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_discovery_failure_does_not_abort_the_tick(
    mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery, mock_read_tool_result
):
    # Finding 4: fetch_discovery_dashboards raising (e.g. CircuitOpenError from the shared
    # TradingView/stock_scanner breaker) must not prevent the rest of the tick -- watchlist
    # symbols should still be processed.
    mock_discovery.side_effect = Exception("circuit open")
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists={"fundamentals"}, is_new_symbol=True)
    mock_read_tool_result.return_value = None
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock(return_value={})

    seen = await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen=set(),
    )
    assert seen == {"AAPL"}
    mock_input_agent.assert_awaited_once()
    mock_graph.ainvoke.assert_awaited_once()
