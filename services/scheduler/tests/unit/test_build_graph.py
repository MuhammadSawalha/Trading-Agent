from unittest.mock import patch
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

def test_manager_runs_after_risk():
    graph = build_graph()
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("risk", "manager") in edges

@patch("src.graph.debate._invoke_bear_rebuttal_llm")
@patch("src.graph.debate._invoke_bear_llm")
@patch("src.graph.debate._invoke_bull_llm")
@patch("src.graph.specialists._invoke_llm")
@patch("src.graph.specialists.append_process_history")
@patch("src.graph.specialists.write_agent_output")
@patch("src.graph.specialists.read_agent_output")
def test_compiled_graph_executes_without_error(mock_read, mock_write, mock_append, mock_invoke, mock_bull, mock_bear, mock_rebuttal):
    # Mock DynamoDB operations and LLM calls to avoid AWS dependencies
    mock_read.return_value = None  # Cache miss for all specialists
    mock_invoke.return_value = {"claims": [{"strength": "moderate", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "test"}]}
    mock_bull.return_value = [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull test"}]
    mock_bear.return_value = [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bear test"}]
    mock_rebuttal.return_value = {"rebutted_claim_indices": [], "succeeded_indices": []}

    graph = build_graph()
    result = graph.invoke({"symbol": "AAPL"})
    assert result is not None
    assert result.get("symbol") == "AAPL"
    assert {"fundamentals", "technical", "sentiment", "macro_options"} <= result.keys()
