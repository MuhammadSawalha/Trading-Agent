from typing import Literal, TypedDict

class Claim(TypedDict, total=False):
    strength: Literal["strong", "moderate", "weak"]
    corroborated: bool
    flagged_unreliable: bool
    rebutted_undefended: bool
    source_type: Literal["news", "volume", "other"]
    rationale: str

class SpecialistOutput(TypedDict):
    claims: list[Claim]

class RiskOutput(TypedDict):
    risk_level: Literal["low", "medium", "high"]
    does_not_take_a_directional_stance: bool
    rationale: str

class GraphState(TypedDict, total=False):
    symbol: str
    mcp_client: object  # the MultiServerMCPClient built by Task 14; typed loosely here to avoid a state.py -> mcp_clients.py import cycle
    changed_specialists: set[str]
    is_new_symbol: bool
    tool_data: dict[str, dict]
    fundamentals: SpecialistOutput
    technical: SpecialistOutput
    sentiment: SpecialistOutput
    macro_options: SpecialistOutput
    bull_claims: list[Claim]
    bear_claims: list[Claim]
    risk: RiskOutput
    verdict: dict
