import pytest
from unittest.mock import AsyncMock, patch
from src.graph.manager import manager_node

@pytest.mark.asyncio
@patch("src.graph.manager.write_agent_output")
@patch("src.graph.manager.call_tool", new_callable=AsyncMock)
async def test_manager_calls_mcp_scoring_tool_and_stores_verdict(mock_call_tool, mock_write):
    mock_call_tool.return_value = {"net_score": 42.0, "confidence": 60.0, "label": "Bullish, moderate confidence"}
    state = {
        "symbol": "AAPL", "mcp_client": object(),
        "bull_claims": [{"strength": "strong"}], "bear_claims": [],
        "risk": {"risk_level": "low", "does_not_take_a_directional_stance": True, "rationale": "r"},
    }
    result = await manager_node(state)
    mock_call_tool.assert_awaited_once_with(
        state["mcp_client"], "own", "score_verdict",
        bull_claims=state["bull_claims"], bear_claims=state["bear_claims"], risk_level="low",
    )
    assert result["verdict"]["label"] == "Bullish, moderate confidence"
    mock_write.assert_called_once_with("AAPL", "Manager", result["verdict"])
