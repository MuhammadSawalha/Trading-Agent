from unittest.mock import patch
import pytest
from src.graph.risk import risk_node

@pytest.fixture
def persisted(monkeypatch):
    """Captures risk.py's Dynamo writes so tests never touch AWS."""
    outputs = {}
    history = []
    monkeypatch.setattr("src.graph.risk.write_agent_output",
                        lambda symbol, agent, payload: outputs.__setitem__(agent, payload))
    monkeypatch.setattr("src.graph.risk.append_process_history",
                        lambda symbol, agent, **kwargs: history.append((agent, kwargs["status"])))
    return outputs, history

@patch("src.graph.risk._invoke_risk_llm")
def test_accepts_response_with_neutrality_flag_true(mock_invoke, persisted):
    mock_invoke.return_value = {"risk_level": "medium", "does_not_take_a_directional_stance": True, "rationale": "r"}
    state = {"symbol": "AAPL", "bull_claims": [], "bear_claims": [], "fundamentals": {"claims": []}, "technical": {"claims": []}, "sentiment": {"claims": []}, "macro_options": {"claims": []}}
    result = risk_node(state)
    assert result["risk"]["risk_level"] == "medium"

    outputs, history = persisted
    assert outputs["Risk"] == result["risk"]
    assert history == [("Risk", "started"), ("Risk", "finished")]

@patch("src.graph.risk._invoke_risk_llm")
def test_accepts_response_with_neutrality_flag_false(mock_invoke, persisted):
    # does_not_take_a_directional_stance is the model's own self-report and is kept on the
    # output for visibility only -- it is not a pass/fail gate. A symbol whose risk factors
    # genuinely skew one way (e.g. stretched valuation, deteriorating macro) produces a
    # faithful risk summary that reads as directional almost by construction, so retrying
    # until the model claims neutrality made this node fail deterministically for exactly the
    # symbols where the risk assessment mattered most.
    mock_invoke.return_value = {"risk_level": "high", "does_not_take_a_directional_stance": False, "rationale": "r"}
    state = {"symbol": "AAPL", "bull_claims": [], "bear_claims": [], "fundamentals": {"claims": []}, "technical": {"claims": []}, "sentiment": {"claims": []}, "macro_options": {"claims": []}}
    result = risk_node(state)
    assert result["risk"]["risk_level"] == "high"
    assert mock_invoke.call_count == 1  # no retries

    outputs, history = persisted
    assert outputs["Risk"] == result["risk"]
    assert history == [("Risk", "started"), ("Risk", "finished")]

@patch("src.graph.risk._invoke_risk_llm")
def test_marks_failed_on_llm_exception(mock_invoke, persisted):
    mock_invoke.side_effect = RuntimeError("boom")
    state = {"symbol": "AAPL", "bull_claims": [], "bear_claims": [], "fundamentals": {"claims": []}, "technical": {"claims": []}, "sentiment": {"claims": []}, "macro_options": {"claims": []}}
    with pytest.raises(RuntimeError):
        risk_node(state)

    outputs, history = persisted
    assert outputs == {}
    assert history == [("Risk", "started"), ("Risk", "failed")]
