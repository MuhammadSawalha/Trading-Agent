from datetime import datetime, timezone
from typing import Literal
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState
from common.dynamo import write_agent_output, append_process_history

_MAX_ATTEMPTS = 3

class RiskSchemaViolation(Exception):
    pass

class RiskResponse(BaseModel):
    # Constrained rather than a bare str: the MCP scoring tool does a bare
    # _RISK_CONFIDENCE_MULT[risk_level] lookup, so an out-of-vocabulary value from the
    # LLM would KeyError inside the Manager's scoring call.
    risk_level: Literal["low", "medium", "high"]
    does_not_take_a_directional_stance: bool
    rationale: str

def _invoke_risk_llm(state: GraphState) -> dict:
    llm = ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-east-1",
    ).with_structured_output(RiskResponse)
    all_claims = state.get("bull_claims", []) + state.get("bear_claims", [])
    response = llm.invoke([
        {"role": "system", "content": (
            "You are the Risk agent. Synthesize market risk (volatility, macro backdrop, "
            "liquidity, options-implied risk, upcoming events, ownership instability) and "
            "data-reliability risk (cross-source disagreement, unreliable-data flags) into "
            "a single risk_level of low/medium/high. You must NEVER argue a bullish or "
            "bearish direction — set does_not_take_a_directional_stance to true only if "
            "your rationale contains no directional language."
        )},
        {"role": "user", "content": f"Claims under consideration:\n{all_claims}"},
    ])
    return response.model_dump()

def risk_node(state: GraphState) -> dict:
    symbol = state["symbol"]
    append_process_history(symbol, "Risk", reason="pipeline_run", status="started", timestamp=datetime.now(timezone.utc))

    last_result = None
    try:
        for _ in range(_MAX_ATTEMPTS):
            last_result = _invoke_risk_llm(state)
            if last_result["does_not_take_a_directional_stance"]:
                write_agent_output(symbol, "Risk", last_result)
                append_process_history(symbol, "Risk", reason="pipeline_run", status="finished", timestamp=datetime.now(timezone.utc))
                return {"risk": last_result}
        # One terminal "failed" per node invocation, not one per retry attempt.
        raise RiskSchemaViolation(
            f"Risk agent failed directional-neutrality check after {_MAX_ATTEMPTS} attempts: {last_result}"
        )
    except Exception:
        append_process_history(symbol, "Risk", reason="pipeline_run", status="failed", timestamp=datetime.now(timezone.utc))
        raise
