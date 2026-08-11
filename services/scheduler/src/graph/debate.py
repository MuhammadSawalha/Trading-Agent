from datetime import datetime, timezone
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState, Claim
from .specialists import ClaimModel
from common.dynamo import write_agent_output, append_process_history

# Instructs Bull/Bear to carry the scoring-relevant provenance fields through from the
# source specialist claim; without it the model reconstructs claims from scratch and these
# silently default to None, disabling spec §4.5.1's freshness/volume adjustments.
_CARRY_THROUGH_INSTRUCTION = (
    " When a source claim has source_type 'news' or 'volume', carry its news_hours_old, "
    "news_is_primary_entity, volume_ratio, and avg_volume fields through unchanged into "
    "your own claim — do not drop or invent them."
)

def _bedrock_llm():
    return ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-east-1",
    )

class ClaimListResponse(BaseModel):
    claims: list[ClaimModel]

class RebuttalResponse(BaseModel):
    rebutted_claim_indices: list[int]  # which Bull claims Bear attempted to rebut
    succeeded_indices: list[int]       # subset that the judgment call says actually succeeded

def _all_specialist_claims(state: GraphState) -> list[Claim]:
    claims: list[Claim] = []
    for specialist in ["fundamentals", "technical", "sentiment", "macro_options"]:
        claims.extend(state.get(specialist, {}).get("claims", []))
    return claims

def _invoke_bull_llm(claims: list[Claim]) -> list[dict]:
    llm = _bedrock_llm().with_structured_output(ClaimListResponse)
    response = llm.invoke([
        {"role": "system", "content": (
            "Construct the strongest bullish case from these specialist claims. Only use "
            "claims that support a bullish view." + _CARRY_THROUGH_INSTRUCTION
        )},
        {"role": "user", "content": f"Claims:\n{claims}"},
    ])
    return [c.model_dump() for c in response.claims]

def _invoke_bear_llm(claims: list[Claim]) -> list[dict]:
    llm = _bedrock_llm().with_structured_output(ClaimListResponse)
    response = llm.invoke([
        {"role": "system", "content": (
            "Construct the strongest bearish case from these specialist claims. Only use "
            "claims that support a bearish view." + _CARRY_THROUGH_INSTRUCTION
        )},
        {"role": "user", "content": f"Claims:\n{claims}"},
    ])
    return [c.model_dump() for c in response.claims]

def _invoke_bear_rebuttal_llm(bull_claims: list[Claim], bear_claims: list[dict]) -> dict:
    llm = _bedrock_llm().with_structured_output(RebuttalResponse)
    response = llm.invoke([
        {"role": "system", "content": (
            "You are arguing the bear case. For each of the Bull's claims below, either "
            "directly rebut it with evidence from your own claims, or concede it. Then, as "
            "a separate judgment, decide which of your rebuttal attempts actually succeeded "
            "(the Bull's claim is meaningfully undermined) vs. which were weak or unconvincing."
        )},
        {"role": "user", "content": f"Bull claims:\n{bull_claims}\n\nYour bear claims:\n{bear_claims}"},
    ])
    return response.model_dump()

def bull_node(state: GraphState) -> dict:
    symbol = state["symbol"]
    claims = _all_specialist_claims(state)

    append_process_history(symbol, "Bull", reason="pipeline_run", status="started", timestamp=datetime.now(timezone.utc))
    try:
        bull_claims = _invoke_bull_llm(claims)
        # rebutted_undefended is decided solely by the Bear's rebuttal-judgment step; never
        # let the claim-construction call invent it.
        for claim in bull_claims:
            claim["rebutted_undefended"] = False
        write_agent_output(symbol, "Bull", {"claims": bull_claims})
        append_process_history(symbol, "Bull", reason="pipeline_run", status="finished", timestamp=datetime.now(timezone.utc))
    except Exception:
        append_process_history(symbol, "Bull", reason="pipeline_run", status="failed", timestamp=datetime.now(timezone.utc))
        raise
    return {"bull_claims": bull_claims}

def bear_node(state: GraphState) -> dict:
    symbol = state["symbol"]
    claims = _all_specialist_claims(state)

    append_process_history(symbol, "Bear", reason="pipeline_run", status="started", timestamp=datetime.now(timezone.utc))
    try:
        bear_claims = _invoke_bear_llm(claims)
        # The rebuttal step never touches the Bear's own claims, so this flag can only ever
        # be a hallucination on them.
        for claim in bear_claims:
            claim["rebutted_undefended"] = False

        rebuttal = _invoke_bear_rebuttal_llm(state.get("bull_claims", []), bear_claims)

        bull_claims = [dict(c) for c in state.get("bull_claims", [])]
        for idx in rebuttal["succeeded_indices"]:
            if 0 <= idx < len(bull_claims):
                bull_claims[idx]["rebutted_undefended"] = True

        write_agent_output(symbol, "Bear", {"claims": bear_claims})
        # Bear mutates Bull's claims, so re-write Bull's row too — otherwise the persisted
        # AgentOutputs entry goes stale relative to what the Manager actually scores.
        write_agent_output(symbol, "Bull", {"claims": bull_claims})
        append_process_history(symbol, "Bear", reason="pipeline_run", status="finished", timestamp=datetime.now(timezone.utc))
    except Exception:
        append_process_history(symbol, "Bear", reason="pipeline_run", status="failed", timestamp=datetime.now(timezone.utc))
        raise
    return {"bull_claims": bull_claims, "bear_claims": bear_claims}
