import pytest
from src.graph.build_graph import build_graph


@pytest.mark.asyncio
async def test_full_pipeline_executes_in_dependency_order(monkeypatch):
    execution_order = []

    def track(name, return_value):
        def wrapper(*args, **kwargs):
            execution_order.append(name)
            return return_value
        return wrapper

    def track_async(name, return_value):
        async def wrapper(*args, **kwargs):
            execution_order.append(name)
            return return_value
        return wrapper

    monkeypatch.setattr(
        "src.graph.specialists._invoke_llm",
        track("specialist", {"claims": [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "r"}]}),
    )
    monkeypatch.setattr("src.graph.specialists.read_agent_output", lambda *a: None)
    monkeypatch.setattr("src.graph.specialists.write_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("src.graph.specialists.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.graph.debate.write_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("src.graph.debate.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.graph.risk.write_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("src.graph.risk.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.graph.debate._invoke_bull_llm", track("bull", []))
    monkeypatch.setattr("src.graph.debate._invoke_bear_llm", track("bear", []))
    monkeypatch.setattr(
        "src.graph.debate._invoke_bear_rebuttal_llm",
        track("bear_rebuttal", {"rebutted_claim_indices": [], "succeeded_indices": []}),
    )
    monkeypatch.setattr(
        "src.graph.risk._invoke_risk_llm",
        track("risk", {"risk_level": "low", "does_not_take_a_directional_stance": True, "rationale": "r"}),
    )
    monkeypatch.setattr(
        "src.graph.manager.call_tool",
        track_async("manager", {"net_score": 0.0, "confidence": 0.0, "label": "Neutral, no confidence"}),
    )
    monkeypatch.setattr("src.graph.manager.write_agent_output", lambda *a, **k: None)

    graph = build_graph()
    initial_state = {
        "symbol": "AAPL", "mcp_client": object(), "is_new_symbol": True,
        "changed_specialists": {"fundamentals", "technical", "sentiment", "macro_options"},
        "tool_data": {},
    }
    result = await graph.ainvoke(initial_state)

    assert result["verdict"]["label"] == "Neutral, no confidence"
    assert "risk" in result
    assert "bull_claims" in result and "bear_claims" in result

    # Verify the actual dependency order from spec §4: all four specialists
    # complete before bull starts; bull before bear; bear's own claims and its
    # rebuttal judgment before risk; risk before manager.
    last_specialist_idx = max(i for i, n in enumerate(execution_order) if n == "specialist")
    bull_idx = execution_order.index("bull")
    bear_idx = execution_order.index("bear")
    bear_rebuttal_idx = execution_order.index("bear_rebuttal")
    risk_idx = execution_order.index("risk")
    manager_idx = execution_order.index("manager")

    assert last_specialist_idx < bull_idx
    assert bull_idx < bear_idx < bear_rebuttal_idx < risk_idx
    assert risk_idx < manager_idx

    # Exact fire-counts, not just relative order: an order-only check cannot see a node
    # running twice (the historical risk double-fire caused by a stray bull->risk edge).
    assert execution_order.count("specialist") == 4
    for node_name in ("bull", "bear", "bear_rebuttal", "risk", "manager"):
        assert execution_order.count(node_name) == 1
