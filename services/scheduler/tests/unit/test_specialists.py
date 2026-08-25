import pytest
from unittest.mock import MagicMock, patch
from langfuse.langchain import CallbackHandler
from src.graph import specialists as specialists_mod
from src.graph.specialists import ClaimModel, make_specialist_node

def test_claim_model_defaults_rebutted_undefended_to_false():
    # Regression test: Bull/Bear (src/graph/debate.py) always overwrite this field
    # themselves after parsing, so the LLM has no reason to reliably include it -- a
    # missing default made an omission fail Pydantic validation outright and crash the
    # whole pipeline run.
    claim = ClaimModel(strength="strong", corroborated=True, flagged_unreliable=False,
                        source_type="other", rationale="r")
    assert claim.rebutted_undefended is False

def test_skips_llm_call_when_specialist_not_in_changed_set(monkeypatch):
    read_names = []
    def fake_read(symbol, name):
        read_names.append(name)
        return {"claims": [{"strength": "moderate", "rationale": "cached"}]}
    monkeypatch.setattr("src.graph.specialists.read_agent_output", fake_read)
    node = make_specialist_node("fundamentals", "system prompt")
    state = {"symbol": "AAPL", "changed_specialists": {"sentiment"}, "is_new_symbol": False, "tool_data": {}}
    result = node(state)
    assert result["fundamentals"]["claims"][0]["rationale"] == "cached"
    # Dynamo rows are keyed by the capitalized display name, not the lowercase node name.
    assert read_names == ["Fundamentals"]

@patch("src.graph.specialists._invoke_llm")
def test_calls_llm_and_writes_output_when_specialist_changed(mock_invoke, monkeypatch):
    mock_invoke.return_value = {"claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "fresh"}]}
    written = {}
    monkeypatch.setattr("src.graph.specialists.write_agent_output", lambda symbol, name, payload: written.update({name: payload}))
    monkeypatch.setattr("src.graph.specialists.append_process_history", lambda *a, **k: None)

    node = make_specialist_node("fundamentals", "system prompt")
    state = {"symbol": "AAPL", "changed_specialists": {"fundamentals"}, "is_new_symbol": False, "tool_data": {"fundamentals": {}}}
    result = node(state)

    assert result["fundamentals"]["claims"][0]["rationale"] == "fresh"
    # Persisted under the capitalized display name, while the GraphState key stays lowercase.
    assert written["Fundamentals"]["claims"][0]["rationale"] == "fresh"

@pytest.fixture
def persisted(monkeypatch):
    """Captures specialists.py's Dynamo writes so tests never touch AWS."""
    outputs = {}
    history = []
    monkeypatch.setattr("src.graph.specialists.write_agent_output",
                        lambda symbol, name, payload: outputs.__setitem__(name, payload))
    monkeypatch.setattr("src.graph.specialists.append_process_history",
                        lambda symbol, name, **kwargs: history.append((name, kwargs["status"])))
    return outputs, history

@patch("src.graph.specialists._invoke_llm")
def test_recovers_from_a_transient_malformed_structured_output_on_retry(mock_invoke, persisted):
    # with_structured_output occasionally has the model return a field in a form that fails
    # Pydantic validation outright (e.g. claims serialized as a string instead of a list) --
    # a format slip, not a real disagreement to reason about. This must not need a whole
    # separate scheduler tick (and some unrelated specialist's data happening to change again)
    # to get a second chance.
    good_output = {"claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False,
                                "rebutted_undefended": False, "source_type": "other", "rationale": "ok"}]}
    mock_invoke.side_effect = [ValueError("claims: Input should be a valid list"), good_output]

    node = make_specialist_node("macro_options", "system prompt")
    state = {"symbol": "AAPL", "changed_specialists": {"macro_options"}, "is_new_symbol": False, "tool_data": {}}
    result = node(state)

    assert result["macro_options"]["claims"][0]["rationale"] == "ok"
    assert mock_invoke.call_count == 2
    outputs, history = persisted
    assert outputs["Macro_Options"] == result["macro_options"]
    # One terminal started/finished pair for the whole attempt loop -- not one per attempt.
    assert history == [("Macro_Options", "started"), ("Macro_Options", "finished")]

@patch("src.graph.specialists._invoke_llm")
def test_gives_up_and_records_a_single_failure_after_exhausting_retries(mock_invoke, persisted):
    mock_invoke.side_effect = ValueError("claims: Input should be a valid list")

    node = make_specialist_node("macro_options", "system prompt")
    state = {"symbol": "AAPL", "changed_specialists": {"macro_options"}, "is_new_symbol": False, "tool_data": {}}
    with pytest.raises(ValueError):
        node(state)

    assert mock_invoke.call_count == 3  # _MAX_ATTEMPTS, not unbounded
    outputs, history = persisted
    assert "Macro_Options" not in outputs
    # One terminal started/failed pair for the whole attempt loop -- not one per attempt.
    assert history == [("Macro_Options", "started"), ("Macro_Options", "failed")]

@patch("src.graph.specialists.ChatBedrockConverse")
def test_invoke_llm_wires_langfuse_config_into_invoke_call(mock_chat_cls):
    # _get_llm is @functools.lru_cache(maxsize=1): the Langfuse config can't be baked into
    # the cached LLM constructor, it must be passed into the per-call .invoke(config=...).
    specialists_mod._get_llm.cache_clear()
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(model_dump=lambda: {"claims": []})
    mock_chat_cls.return_value.with_structured_output.return_value = mock_llm

    try:
        specialists_mod._invoke_llm("Fundamentals system prompt", {"k": "v"}, "AAPL")
    finally:
        specialists_mod._get_llm.cache_clear()

    _, kwargs = mock_llm.invoke.call_args
    config = kwargs["config"]
    # Sessions are grouped by symbol, per the plan's intent.
    assert config["metadata"] == {"langfuse_session_id": "AAPL"}
    assert config["tags"] == ["Fundamentals system prompt"[:20]]
    assert len(config["callbacks"]) == 1
    assert isinstance(config["callbacks"][0], CallbackHandler)

def test_returns_only_specialist_output_not_full_state(monkeypatch):
    """Regression guard: ensure node returns partial state (only its own key), not full state echo."""
    monkeypatch.setattr("src.graph.specialists.read_agent_output", lambda symbol, name: {"claims": [{"strength": "moderate", "rationale": "cached"}]})
    node = make_specialist_node("fundamentals", "system prompt")
    state = {
        "symbol": "AAPL",
        "changed_specialists": {"sentiment"},
        "is_new_symbol": False,
        "tool_data": {},
        "mcp_client": "sentinel_value"
    }
    result = node(state)

    # Result should only contain the specialist output key, not unrelated state keys
    assert "fundamentals" in result
    assert "mcp_client" not in result
    assert "symbol" not in result
    assert "tool_data" not in result
