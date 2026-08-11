from typing import Literal, TypedDict

class Claim(TypedDict, total=False):
    strength: Literal["strong", "moderate", "weak"]
    corroborated: bool
    flagged_unreliable: bool
    rebutted_undefended: bool
    source_type: Literal["news", "volume", "other"]
    rationale: str
    # Populated only for source_type="news" (Sentiment) / "volume" (Technical) claims — Task 3's
    # score_claim reads these for the freshness/centrality and log-compressed volume adjustments
    # (spec §4.5.1). None for every other claim; score_claim treats missing volume/news fields
    # as "no adjustment" rather than crashing.
    news_hours_old: float | None
    news_is_primary_entity: bool | None
    volume_ratio: float | None
    avg_volume: float | None

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
