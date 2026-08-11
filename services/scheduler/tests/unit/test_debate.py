import pytest
from unittest.mock import patch
from src.graph.debate import bull_node, bear_node

def _all_specialist_claims():
    return {"claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "r"}]}

@pytest.fixture
def persisted(monkeypatch):
    """Captures debate.py's Dynamo writes so tests never touch AWS."""
    outputs = {}
    history = []
    monkeypatch.setattr("src.graph.debate.write_agent_output",
                        lambda symbol, agent, payload: outputs.__setitem__(agent, payload))
    monkeypatch.setattr("src.graph.debate.append_process_history",
                        lambda symbol, agent, **kwargs: history.append((agent, kwargs["status"])))
    return outputs, history

@patch("src.graph.debate._invoke_bull_llm")
def test_bull_node_collects_claims_from_all_specialists(mock_invoke, persisted):
    mock_invoke.return_value = [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}]
    state = {"symbol": "AAPL", "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
             "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims()}
    result = bull_node(state)
    assert len(result["bull_claims"]) == 1

    outputs, history = persisted
    assert outputs["Bull"] == {"claims": result["bull_claims"]}
    assert history == [("Bull", "started"), ("Bull", "finished")]

@patch("src.graph.debate._invoke_bull_llm")
def test_bull_node_forces_rebutted_undefended_false(mock_invoke, persisted):
    """Only the Bear's rebuttal judgment may set this flag; a hallucinated true from the
    claim-construction call must not survive."""
    mock_invoke.return_value = [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": True, "source_type": "other", "rationale": "bull case"}]
    state = {"symbol": "AAPL", "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
             "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims()}
    result = bull_node(state)
    assert result["bull_claims"][0]["rebutted_undefended"] is False

@patch("src.graph.debate._invoke_bull_llm")
def test_bull_node_logs_failed_status_when_llm_raises(mock_invoke, persisted):
    mock_invoke.side_effect = RuntimeError("bedrock down")
    state = {"symbol": "AAPL", "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
             "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims()}
    with pytest.raises(RuntimeError):
        bull_node(state)
    _, history = persisted
    assert history == [("Bull", "started"), ("Bull", "failed")]

@patch("src.graph.debate._invoke_bear_rebuttal_llm")
@patch("src.graph.debate._invoke_bear_llm")
def test_bear_node_forces_rebutted_undefended_false_on_its_own_claims(mock_bear, mock_rebuttal, persisted):
    mock_bear.return_value = [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": True, "source_type": "other", "rationale": "bear case"}]
    mock_rebuttal.return_value = {"rebutted_claim_indices": [], "succeeded_indices": []}
    state = {
        "symbol": "AAPL",
        "bull_claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}],
        "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
        "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims(),
    }
    result = bear_node(state)
    assert result["bear_claims"][0]["rebutted_undefended"] is False

@patch("src.graph.debate._invoke_bear_rebuttal_llm")
@patch("src.graph.debate._invoke_bear_llm")
def test_bear_node_persists_both_its_claims_and_the_mutated_bull_claims(mock_bear, mock_rebuttal, persisted):
    mock_bear.return_value = [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bear case"}]
    mock_rebuttal.return_value = {"rebutted_claim_indices": [0], "succeeded_indices": [0]}
    state = {
        "symbol": "AAPL",
        "bull_claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}],
        "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
        "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims(),
    }
    result = bear_node(state)

    outputs, history = persisted
    assert outputs["Bear"] == {"claims": result["bear_claims"]}
    # Bull's stored row is refreshed with the rebuttal outcome so it doesn't go stale
    # relative to what the Manager scores.
    assert outputs["Bull"] == {"claims": result["bull_claims"]}
    assert outputs["Bull"]["claims"][0]["rebutted_undefended"] is True
    assert history == [("Bear", "started"), ("Bear", "finished")]

@patch("src.graph.debate._invoke_bear_rebuttal_llm")
@patch("src.graph.debate._invoke_bear_llm")
def test_bear_node_marks_undefended_rebuttals_on_bull_claims(mock_bear, mock_rebuttal, persisted):
    mock_bear.return_value = [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bear case"}]
    mock_rebuttal.return_value = {"rebutted_claim_indices": [0], "succeeded_indices": [0]}
    state = {
        "symbol": "AAPL",
        "bull_claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}],
        "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
        "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims(),
    }
    result = bear_node(state)
    assert result["bull_claims"][0]["rebutted_undefended"] is True
    assert len(result["bear_claims"]) == 1
