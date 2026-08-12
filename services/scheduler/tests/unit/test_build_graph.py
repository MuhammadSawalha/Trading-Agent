from unittest.mock import patch, AsyncMock
from src.graph.build_graph import build_graph

def test_graph_nodes_include_all_pipeline_stages():
    graph = build_graph()
    node_names = set(graph.get_graph().nodes.keys())
    expected = {"fundamentals", "technical", "sentiment", "macro_options", "bull", "bear", "risk", "manager"}
    assert expected.issubset(node_names)

def test_specialists_run_before_bull_and_bear():
    graph = build_graph()
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    for specialist in ["fundamentals", "technical", "sentiment", "macro_options"]:
        assert any(src == specialist and dst in ("bull", "bear") for src, dst in edges)

def test_debate_topology_is_sequential_bull_then_bear():
    """Regression guard for the two execution-order bugs fixed during the final review:
    a direct bull->risk edge (which let risk fire twice) and specialist->bear edges
    (which let bear run before bull's claims existed)."""
    graph = build_graph()
    edges = {(e.source, e.target) for e in graph.get_graph().edges}

    assert ("bull", "risk") not in edges
    for specialist in ["fundamentals", "technical", "sentiment", "macro_options"]:
        assert (specialist, "bear") not in edges

    # bear's only incoming edge is from bull
    assert {src for src, dst in edges if dst == "bear"} == {"bull"}
    assert ("bull", "bear") in edges
    assert ("bear", "risk") in edges

def test_manager_runs_after_risk():
    graph = build_graph()
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("risk", "manager") in edges

@patch("src.graph.manager.append_process_history")
@patch("src.graph.manager.write_agent_output")
@patch("src.graph.manager.call_tool", new_callable=AsyncMock)
@patch("src.graph.risk.append_process_history")
@patch("src.graph.risk.write_agent_output")
@patch("src.graph.risk._invoke_risk_llm")
@patch("src.graph.debate.append_process_history")
@patch("src.graph.debate.write_agent_output")
@patch("src.graph.debate._invoke_bear_rebuttal_llm")
@patch("src.graph.debate._invoke_bear_llm")
@patch("src.graph.debate._invoke_bull_llm")
@patch("src.graph.specialists._invoke_llm")
@patch("src.graph.specialists.append_process_history")
@patch("src.graph.specialists.write_agent_output")
@patch("src.graph.specialists.read_agent_output")
async def test_compiled_graph_executes_without_error(mock_read, mock_write, mock_append, mock_invoke, mock_bull, mock_bear, mock_rebuttal, mock_debate_write, mock_debate_append, mock_risk, mock_risk_write, mock_risk_append, mock_call_tool, mock_manager_write, mock_manager_append):
    # Mock DynamoDB operations and LLM calls to avoid AWS dependencies
    mock_read.return_value = None  # Cache miss for all specialists
    mock_invoke.return_value = {"claims": [{"strength": "moderate", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "test"}]}
    mock_bull.return_value = [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull test"}]
    mock_bear.return_value = [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bear test"}]
    mock_rebuttal.return_value = {"rebutted_claim_indices": [], "succeeded_indices": []}
    mock_risk.return_value = {"risk_level": "medium", "does_not_take_a_directional_stance": True, "rationale": "moderate risk"}
    mock_call_tool.return_value = {"net_score": 0.0, "confidence": 0.0, "label": "Neutral, no confidence"}

    graph = build_graph()
    result = await graph.ainvoke({"symbol": "AAPL", "mcp_client": object()})
    assert result is not None
    assert result.get("symbol") == "AAPL"
    assert {"fundamentals", "technical", "sentiment", "macro_options"} <= result.keys()
