import logging
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo
import src.loop
from src.loop import scheduler_tick, run_forever
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

@pytest.mark.asyncio
@patch("src.loop.read_agent_output")
@patch("src.loop.read_watchlist")
@patch("src.loop.scheduler_tick", new_callable=AsyncMock)
async def test_run_forever_seeds_seen_from_existing_manager_output(
    mock_tick, mock_watchlist, mock_read_agent_output
):
    # Finding 1: an in-memory-only `seen` set means every process restart makes run_forever
    # treat the whole watchlist as brand-new on the first tick, bypassing cadence/extended-
    # hours gating (is_new_symbol=True short-circuits _is_due) for every symbol at once. Seed
    # `seen` on startup from symbols that already have a Manager verdict (durable proof they've
    # been through the pipeline before).
    mock_watchlist.return_value = ["AAPL", "MSFT", "TSLA"]
    mock_read_agent_output.side_effect = lambda symbol, agent_name: (
        {"verdict": "buy"} if symbol in {"AAPL", "MSFT"} else None
    )
    mock_tick.return_value = set()

    class _StopLoop(Exception):
        pass

    async def fake_sleep(seconds):
        raise _StopLoop()

    with patch("asyncio.sleep", side_effect=fake_sleep):
        with pytest.raises(_StopLoop):
            await run_forever(mcp_client=object(), tick_interval_seconds=1)

    mock_tick.assert_awaited_once()
    previously_seen = mock_tick.call_args.args[3]
    assert previously_seen == {"AAPL", "MSFT"}

@pytest.mark.asyncio
@patch("src.loop.record_heartbeat")
@patch("src.loop.read_agent_output")
@patch("src.loop.read_watchlist")
@patch("src.loop.scheduler_tick", new_callable=AsyncMock)
async def test_run_forever_records_a_heartbeat_before_the_first_tick_completes(
    mock_tick, mock_watchlist, mock_read_agent_output, mock_record_heartbeat
):
    # Final review Finding 2: on a cold start, the first tick (discovery fetch + input-data-
    # agent + full pipeline for every "new" watchlist symbol) can take a long time, and the
    # existing per-tick record_heartbeat call (after scheduler_tick returns, just before
    # asyncio.sleep -- unchanged by this fix) doesn't land until that whole first tick
    # finishes. /healthz would 503 for that entire startup window. A heartbeat recorded
    # immediately before the `while True:` loop starts closes that gap without weakening the
    # per-tick call's ability to catch a genuinely hung loop (a tick that never returns still
    # means no *subsequent* heartbeat lands, so staleness still fires eventually).
    mock_watchlist.return_value = []
    mock_read_agent_output.return_value = None

    call_order: list[str] = []
    mock_record_heartbeat.side_effect = lambda now: call_order.append("heartbeat")

    async def tracked_tick(*args, **kwargs):
        call_order.append("tick")
        return set()

    mock_tick.side_effect = tracked_tick

    class _StopLoop(Exception):
        pass

    async def fake_sleep(seconds):
        raise _StopLoop()

    with patch("asyncio.sleep", side_effect=fake_sleep):
        with pytest.raises(_StopLoop):
            await run_forever(mcp_client=object(), tick_interval_seconds=1)

    # A heartbeat lands before the first tick even starts (pre-loop call), and again after it
    # completes (the existing, unchanged per-tick call) -- two total by the time sleep is hit.
    assert call_order[0] == "heartbeat"
    assert call_order == ["heartbeat", "tick", "heartbeat"]
    assert mock_record_heartbeat.call_count == 2

@pytest.mark.asyncio
@patch("src.loop.read_tool_result")
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_global_tool_data_is_read_once_per_tick_not_once_per_symbol(
    mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery, mock_read_tool_result
):
    # Finding 2: the 12 per_symbol=False FETCH_PLAN entries all resolve to the same
    # GLOBAL#{tool_name} pk regardless of symbol -- with 2 symbols in the watchlist, each
    # GLOBAL# pk must still only be read once for the whole tick, not once per symbol.
    mock_watchlist.return_value = ["AAPL", "MSFT"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists={"macro_options"}, is_new_symbol=True)
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock(return_value={})
    mock_read_tool_result.return_value = None

    await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen=set(),
    )

    global_pks_read = [
        call.args[0] for call in mock_read_tool_result.call_args_list if call.args[0].startswith("GLOBAL#")
    ]
    assert len(global_pks_read) > 0  # sanity: global entries were read at all
    assert len(global_pks_read) == len(set(global_pks_read))  # but never more than once each

@pytest.mark.asyncio
@patch("src.loop.asyncio.to_thread", new_callable=AsyncMock)
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_tool_data_reads_are_offloaded_to_a_thread(
    mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery, mock_to_thread
):
    # Finding 3: read_tool_result is blocking boto3 I/O -- the batch reads for the hoisted
    # globals and for each symbol must run via asyncio.to_thread, not inline in the coroutine.
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists={"fundamentals"}, is_new_symbol=True)
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock(return_value={})
    mock_to_thread.return_value = {}

    await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen=set(),
    )

    offloaded_funcs = [call.args[0] for call in mock_to_thread.call_args_list]
    assert src.loop._read_global_tool_data in offloaded_funcs
    assert src.loop._read_symbol_tool_data in offloaded_funcs

@pytest.mark.asyncio
@patch("src.loop.read_tool_result")
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_missing_tool_data_pk_logs_debug(
    mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery, mock_read_tool_result, caplog
):
    # Finding 5: a pk reading back None (not yet fetched) must be diagnosable from logs, at
    # debug level (expected/self-healing, not an operational warning).
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists={"fundamentals"}, is_new_symbol=True)
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock(return_value={})
    mock_read_tool_result.return_value = None  # nothing cached yet for any pk

    with caplog.at_level(logging.DEBUG, logger="src.loop"):
        await scheduler_tick(
            mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
            now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen=set(),
        )

    debug_messages = [record.getMessage() for record in caplog.records if record.levelno == logging.DEBUG]
    assert any("AAPL" in m and "finnhub_company_profile" in m and "fundamentals" in m for m in debug_messages)
