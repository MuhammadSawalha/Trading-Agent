from .state import GraphState
from ..mcp_clients import call_tool
from common.dynamo import write_agent_output


async def manager_node(state: GraphState) -> dict:
    verdict = await call_tool(
        state["mcp_client"], "own", "score_verdict",
        bull_claims=state.get("bull_claims", []),
        bear_claims=state.get("bear_claims", []),
        risk_level=state["risk"]["risk_level"],
    )
    write_agent_output(state["symbol"], "Manager", verdict)
    return {"verdict": verdict}
