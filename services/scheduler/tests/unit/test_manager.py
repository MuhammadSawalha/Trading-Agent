import pytest
from unittest.mock import AsyncMock, patch
from src.graph.manager import manager_node

@pytest.fixture
def history(monkeypatch):
    """Captures manager.py's ProcessHistory writes so tests never touch AWS."""
    entries = []
    monkeypatch.setattr("src.graph.manager.append_process_history",
                        lambda symbol, agent, **kwargs: entries.append((agent, kwargs["status"])))
    return entries

@pytest.fixture
def state():
    return {
        "symbol": "AAPL", "mcp_client": object(),
        "bull_claims": [{"strength": "strong"}], "bear_claims": [],
        "risk": {"risk_level": "low", "does_not_take_a_directional_stance": True, "rationale": "r"},
    }

@pytest.mark.asyncio
@patch("src.graph.manager.write_agent_output")
@patch("src.graph.manager.call_tool", new_callable=AsyncMock)
async def test_manager_calls_mcp_scoring_tool_and_stores_verdict(mock_call_tool, mock_write, state, history):
    mock_call_tool.return_value = {"net_score": 42.0, "confidence": 60.0, "label": "Bullish, moderate confidence"}
    result = await manager_node(state)
    mock_call_tool.assert_awaited_once_with(
        state["mcp_client"], "own", "score_verdict",
        bull_claims=state["bull_claims"], bear_claims=state["bear_claims"], risk_level="low",
    )
    assert result["verdict"]["label"] == "Bullish, moderate confidence"
    mock_write.assert_called_once_with("AAPL", "Manager", result["verdict"])

@pytest.mark.asyncio
@patch("src.graph.manager.write_agent_output")
@patch("src.graph.manager.call_tool", new_callable=AsyncMock)
async def test_manager_records_started_then_finished_in_process_history(mock_call_tool, mock_write, state, history):
    # Without these the Manager's "last updated" is permanently null in the
    # detail endpoint and the pipeline visualizer never sees a Manager node.
    mock_call_tool.return_value = {"net_score": 42.0, "confidence": 60.0, "label": "Bullish, moderate confidence"}
    await manager_node(state)
    assert history == [("Manager", "started"), ("Manager", "finished")]

@pytest.mark.asyncio
@patch("src.graph.manager.write_agent_output")
@patch("src.graph.manager.call_tool", new_callable=AsyncMock)
async def test_manager_records_failed_and_reraises_when_scoring_fails(mock_call_tool, mock_write, state, history):
    mock_call_tool.side_effect = RuntimeError("MCP server unreachable")
    with pytest.raises(RuntimeError):
        await manager_node(state)
    assert history == [("Manager", "started"), ("Manager", "failed")]
    mock_write.assert_not_called()
