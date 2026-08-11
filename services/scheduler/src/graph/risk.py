from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState, RiskOutput

_MAX_ATTEMPTS = 3

class RiskSchemaViolation(Exception):
    pass

class RiskResponse(BaseModel):
    risk_level: str
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
    last_result = None
    for _ in range(_MAX_ATTEMPTS):
        last_result = _invoke_risk_llm(state)
        if last_result["does_not_take_a_directional_stance"]:
            return {"risk": last_result}
    raise RiskSchemaViolation(
        f"Risk agent failed directional-neutrality check after {_MAX_ATTEMPTS} attempts: {last_result}"
    )
