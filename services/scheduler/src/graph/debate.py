from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState, Claim

def _bedrock_llm():
    return ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-east-1",
    )

class ClaimListResponse(BaseModel):
    claims: list[dict]

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
        {"role": "system", "content": "Construct the strongest bullish case from these specialist claims. Only use claims that support a bullish view."},
        {"role": "user", "content": f"Claims:\n{claims}"},
    ])
    return response.claims

def _invoke_bear_llm(claims: list[Claim]) -> list[dict]:
    llm = _bedrock_llm().with_structured_output(ClaimListResponse)
    response = llm.invoke([
        {"role": "system", "content": "Construct the strongest bearish case from these specialist claims. Only use claims that support a bearish view."},
        {"role": "user", "content": f"Claims:\n{claims}"},
    ])
    return response.claims

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
    claims = _all_specialist_claims(state)
    return {"bull_claims": _invoke_bull_llm(claims)}

def bear_node(state: GraphState) -> dict:
    claims = _all_specialist_claims(state)
    bear_claims = _invoke_bear_llm(claims)
    rebuttal = _invoke_bear_rebuttal_llm(state.get("bull_claims", []), bear_claims)

    bull_claims = [dict(c) for c in state.get("bull_claims", [])]
    for idx in rebuttal["succeeded_indices"]:
        if idx < len(bull_claims):
            bull_claims[idx]["rebutted_undefended"] = True

    return {"bull_claims": bull_claims, "bear_claims": bear_claims}
