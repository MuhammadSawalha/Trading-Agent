from datetime import datetime, timezone
from typing import Literal
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState
from common.dynamo import write_agent_output, append_process_history

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
            "your rationale contains no directional language.\n\n"
            "Directional language includes praising or criticizing the company's quality, "
            "fundamentals, or valuation — e.g. 'strong margins', 'exceptional ROE', "
            "'overvalued', 'fortress balance sheet', 'attractive entry point'. Never restate "
            "a claim's bullish or bearish framing, even while calling it a risk input. "
            "Instead, name only the risk itself and its magnitude/uncertainty — e.g. write "
            "'valuation multiples imply high sensitivity to a growth deceleration' rather "
            "than 'valuation is stretched/overvalued'; write 'earnings depend heavily on a "
            "narrow set of margin and growth metrics' rather than 'fundamentals are strong "
            "but priced in'. If you catch yourself characterizing whether the company is "
            "doing well or poorly, rewrite the sentence before responding."
        )},
        {"role": "user", "content": f"Claims under consideration:\n{all_claims}"},
    ])
    return response.model_dump()

def risk_node(state: GraphState) -> dict:
    symbol = state["symbol"]
    append_process_history(symbol, "Risk", reason="pipeline_run", status="started", timestamp=datetime.now(timezone.utc))

    try:
        result = _invoke_risk_llm(state)
    except Exception:
        append_process_history(symbol, "Risk", reason="pipeline_run", status="failed", timestamp=datetime.now(timezone.utc))
        raise

    # does_not_take_a_directional_stance is the model's own self-report, kept on the output for
    # visibility -- it is NOT used to gate/retry. A faithful risk summary for a symbol whose risk
    # factors genuinely skew one way (e.g. stretched valuation, deteriorating macro) will read as
    # bearish-leaning almost by construction, so treating that self-report as a hard pass/fail
    # made this node fail deterministically (not just occasionally) for exactly the symbols where
    # risk is most worth surfacing -- the opposite of what the check was meant to protect against.
    write_agent_output(symbol, "Risk", result)
    append_process_history(symbol, "Risk", reason="pipeline_run", status="finished", timestamp=datetime.now(timezone.utc))
    return {"risk": result}
