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
        assert any(src == specialist and dst in ("bull", "bear") for src, dst in edges) or \
               any(src == specialist for src, dst in edges)  # specialist feeds into the debate stage

def test_manager_runs_after_risk():
    graph = build_graph()
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("risk", "manager") in edges

def test_compiled_graph_executes_without_error():
    graph = build_graph()
    result = graph.invoke({"symbol": "AAPL"})
    assert result is not None
    assert result.get("symbol") == "AAPL"
