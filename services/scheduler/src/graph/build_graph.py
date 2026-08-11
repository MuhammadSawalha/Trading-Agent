from langgraph.graph import StateGraph, START, END
from .state import GraphState

def _stub(name: str):
    def node(state: GraphState) -> dict:
        return {}
    node.__name__ = name
    return node

def build_graph():
    builder = StateGraph(GraphState)

    for name in ["fundamentals", "technical", "sentiment", "macro_options", "bull", "bear", "risk", "manager"]:
        builder.add_node(name, _stub(name))

    for specialist in ["fundamentals", "technical", "sentiment", "macro_options"]:
        builder.add_edge(START, specialist)
        builder.add_edge(specialist, "bull")
        builder.add_edge(specialist, "bear")

    builder.add_edge("bull", "risk")
    builder.add_edge("bear", "risk")
    builder.add_edge("risk", "manager")
    builder.add_edge("manager", END)

    return builder.compile()
