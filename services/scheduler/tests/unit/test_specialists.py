import pytest
from unittest.mock import MagicMock, patch
from src.graph.specialists import make_specialist_node

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
