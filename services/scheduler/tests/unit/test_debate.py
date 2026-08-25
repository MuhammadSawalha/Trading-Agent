import pytest
from unittest.mock import MagicMock, patch
from langfuse.langchain import CallbackHandler
from src.graph import debate as debate_mod
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

@patch("src.graph.debate._invoke_bull_llm")
def test_bull_node_recovers_from_a_transient_malformed_structured_output_on_retry(mock_invoke, persisted):
    # Regression test: a Bedrock structured-output response omitting rebutted_undefended
    # on some claims (a required field with no default at the time) crashed the whole
    # pipeline run for the symbol with no retry. Must recover like the specialist nodes do.
    good_claims = [{"strength": "strong", "corroborated": True, "flagged_unreliable": False,
                     "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}]
    mock_invoke.side_effect = [ValueError("claims.0.rebutted_undefended: Field required"), good_claims]
    state = {"symbol": "AAPL", "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
             "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims()}

    result = bull_node(state)

    assert result["bull_claims"] == good_claims
    assert mock_invoke.call_count == 2
    _, history = persisted
    # One terminal started/finished pair for the whole attempt loop -- not one per attempt.
    assert history == [("Bull", "started"), ("Bull", "finished")]

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

@patch("src.graph.debate._invoke_bear_rebuttal_llm")
@patch("src.graph.debate._invoke_bear_llm")
def test_bear_node_recovers_from_a_transient_malformed_structured_output_on_retry(mock_bear, mock_rebuttal, persisted):
    good_claims = [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False,
                     "rebutted_undefended": False, "source_type": "other", "rationale": "bear case"}]
    mock_bear.side_effect = [ValueError("claims.0.rebutted_undefended: Field required"), good_claims]
    mock_rebuttal.return_value = {"rebutted_claim_indices": [], "succeeded_indices": []}
    state = {
        "symbol": "AAPL",
        "bull_claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}],
        "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
        "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims(),
    }

    result = bear_node(state)

    assert result["bear_claims"] == good_claims
    assert mock_bear.call_count == 2
    _, history = persisted
    assert history == [("Bear", "started"), ("Bear", "finished")]

@patch("src.graph.debate._invoke_bear_rebuttal_llm")
@patch("src.graph.debate._invoke_bear_llm")
def test_bear_node_gives_up_and_records_a_single_failure_after_exhausting_retries(mock_bear, mock_rebuttal, persisted):
    mock_bear.side_effect = ValueError("claims.0.rebutted_undefended: Field required")
    state = {
        "symbol": "AAPL",
        "bull_claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}],
        "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
        "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims(),
    }

    with pytest.raises(ValueError):
        bear_node(state)

    assert mock_bear.call_count == 3  # _MAX_ATTEMPTS, not unbounded
    mock_rebuttal.assert_not_called()
    outputs, history = persisted
    assert "Bear" not in outputs
    assert history == [("Bear", "started"), ("Bear", "failed")]

@patch("src.graph.debate.ChatBedrockConverse")
def test_invoke_bull_llm_wires_langfuse_config_into_invoke_call(mock_chat_cls):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(claims=[])
    mock_chat_cls.return_value.with_structured_output.return_value = mock_llm

    debate_mod._invoke_bull_llm([], "AAPL")

    _, kwargs = mock_llm.invoke.call_args
    config = kwargs["config"]
    assert config["metadata"] == {"langfuse_session_id": "AAPL"}
    assert len(config["callbacks"]) == 1
    assert isinstance(config["callbacks"][0], CallbackHandler)

@patch("src.graph.debate.ChatBedrockConverse")
def test_invoke_bear_llm_wires_langfuse_config_into_invoke_call(mock_chat_cls):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(claims=[])
    mock_chat_cls.return_value.with_structured_output.return_value = mock_llm

    debate_mod._invoke_bear_llm([], "MSFT")

    _, kwargs = mock_llm.invoke.call_args
    config = kwargs["config"]
    assert config["metadata"] == {"langfuse_session_id": "MSFT"}
    assert len(config["callbacks"]) == 1
    assert isinstance(config["callbacks"][0], CallbackHandler)

@patch("src.graph.debate.ChatBedrockConverse")
def test_invoke_bear_rebuttal_llm_wires_langfuse_config_into_invoke_call(mock_chat_cls):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        model_dump=lambda: {"rebutted_claim_indices": [], "succeeded_indices": []}
    )
    mock_chat_cls.return_value.with_structured_output.return_value = mock_llm

    debate_mod._invoke_bear_rebuttal_llm([], [], "GOOG")

    _, kwargs = mock_llm.invoke.call_args
    config = kwargs["config"]
    # Every LLM call in a symbol's pipeline run groups under that symbol's session,
    # including the rebuttal step.
    assert config["metadata"] == {"langfuse_session_id": "GOOG"}
    assert len(config["callbacks"]) == 1
    assert isinstance(config["callbacks"][0], CallbackHandler)
