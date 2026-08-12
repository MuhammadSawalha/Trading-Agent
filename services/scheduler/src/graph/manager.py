from datetime import datetime, timezone
from .state import GraphState
from ..mcp_clients import call_tool
from common.dynamo import write_agent_output, append_process_history


async def manager_node(state: GraphState) -> dict:
    symbol = state["symbol"]
    # append_process_history is synchronous and is called un-awaited in every
    # other node (specialists, debate, risk) regardless of whether the node
    # itself is async; kept consistent here.
    append_process_history(symbol, "Manager", reason="pipeline_run", status="started", timestamp=datetime.now(timezone.utc))

    try:
        verdict = await call_tool(
            state["mcp_client"], "own", "score_verdict",
            bull_claims=state.get("bull_claims", []),
            bear_claims=state.get("bear_claims", []),
            risk_level=state["risk"]["risk_level"],
        )
        write_agent_output(symbol, "Manager", verdict)
        append_process_history(symbol, "Manager", reason="pipeline_run", status="finished", timestamp=datetime.now(timezone.utc))
        return {"verdict": verdict}
    except Exception:
        append_process_history(symbol, "Manager", reason="pipeline_run", status="failed", timestamp=datetime.now(timezone.utc))
        raise
