from langgraph.graph import StateGraph, START, END
from .state import GraphState
from .specialists import make_specialist_node, FUNDAMENTALS_PROMPT, TECHNICAL_PROMPT, SENTIMENT_PROMPT, MACRO_OPTIONS_PROMPT

def _stub(name: str):
    def node(state: GraphState) -> dict:
        return {}
    node.__name__ = name
    return node

def build_graph():
    builder = StateGraph(GraphState)

    # Add specialist nodes (Fundamentals, Technical, Sentiment, Macro/Options)
    builder.add_node("fundamentals", make_specialist_node("fundamentals", FUNDAMENTALS_PROMPT))
    builder.add_node("technical", make_specialist_node("technical", TECHNICAL_PROMPT))
    builder.add_node("sentiment", make_specialist_node("sentiment", SENTIMENT_PROMPT))
    builder.add_node("macro_options", make_specialist_node("macro_options", MACRO_OPTIONS_PROMPT))

    # Add remaining stub nodes (bull, bear, risk, manager)
    for name in ["bull", "bear", "risk", "manager"]:
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
