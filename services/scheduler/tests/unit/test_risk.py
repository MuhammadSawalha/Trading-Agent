from unittest.mock import patch
import pytest
from src.graph.risk import risk_node, RiskSchemaViolation

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
def test_retries_and_eventually_raises_if_neutrality_flag_never_true(mock_invoke, persisted):
    mock_invoke.return_value = {"risk_level": "high", "does_not_take_a_directional_stance": False, "rationale": "r"}
    state = {"symbol": "AAPL", "bull_claims": [], "bear_claims": [], "fundamentals": {"claims": []}, "technical": {"claims": []}, "sentiment": {"claims": []}, "macro_options": {"claims": []}}
    with pytest.raises(RiskSchemaViolation):
        risk_node(state)
    assert mock_invoke.call_count == 3  # bounded retries, per spec §10

    outputs, history = persisted
    assert outputs == {}  # nothing persisted for a response that never passed the check
    # One terminal status per node invocation, not one per retry attempt.
    assert history == [("Risk", "started"), ("Risk", "failed")]

@patch("src.graph.risk._invoke_risk_llm")
def test_succeeds_on_second_attempt_after_one_violation(mock_invoke, persisted):
    mock_invoke.side_effect = [
        {"risk_level": "low", "does_not_take_a_directional_stance": False, "rationale": "bad"},
        {"risk_level": "low", "does_not_take_a_directional_stance": True, "rationale": "good"},
    ]
    state = {"symbol": "AAPL", "bull_claims": [], "bear_claims": [], "fundamentals": {"claims": []}, "technical": {"claims": []}, "sentiment": {"claims": []}, "macro_options": {"claims": []}}
    result = risk_node(state)
    assert result["risk"]["rationale"] == "good"
