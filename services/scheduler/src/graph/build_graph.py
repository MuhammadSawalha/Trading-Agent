from langgraph.graph import StateGraph, START, END
from .state import GraphState
from .specialists import make_specialist_node, FUNDAMENTALS_PROMPT, TECHNICAL_PROMPT, SENTIMENT_PROMPT, MACRO_OPTIONS_PROMPT
from .debate import bull_node, bear_node
from .risk import risk_node
from .manager import manager_node

def build_graph():
    builder = StateGraph(GraphState)

    # Add specialist nodes (Fundamentals, Technical, Sentiment, Macro/Options)
    builder.add_node("fundamentals", make_specialist_node("fundamentals", FUNDAMENTALS_PROMPT))
    builder.add_node("technical", make_specialist_node("technical", TECHNICAL_PROMPT))
    builder.add_node("sentiment", make_specialist_node("sentiment", SENTIMENT_PROMPT))
    builder.add_node("macro_options", make_specialist_node("macro_options", MACRO_OPTIONS_PROMPT))

    # Add debate and remaining nodes (risk, manager)
    builder.add_node("bull", bull_node)
    builder.add_node("bear", bear_node)
    builder.add_node("risk", risk_node)
    builder.add_node("manager", manager_node)

    for specialist in ["fundamentals", "technical", "sentiment", "macro_options"]:
        builder.add_edge(START, specialist)
        builder.add_edge(specialist, "bull")

    builder.add_edge("bull", "bear")
    builder.add_edge("bear", "risk")
    builder.add_edge("risk", "manager")
    builder.add_edge("manager", END)

    return builder.compile()
