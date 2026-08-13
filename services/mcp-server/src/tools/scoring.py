import math
from typing import Literal, TypedDict

class Claim(TypedDict, total=False):
    strength: Literal["strong", "moderate", "weak"]
    corroborated: bool
    flagged_unreliable: bool
    rebutted_undefended: bool
    source_type: Literal["news", "volume", "other"]
    news_hours_old: float | None
    news_is_primary_entity: bool | None
    volume_ratio: float | None
    avg_volume: float | None

class Verdict(TypedDict):
    net_score: float
    confidence: float
    label: str

_BASE_STRENGTH = {"strong": 3.0, "moderate": 2.0, "weak": 1.0}
_CORROBORATION_BONUS = 1.5
_UNRELIABLE_PENALTY = 0.5
_REBUTTED_UNDEFENDED_PENALTY = 0.25
_NEWS_FRESHNESS_FLOOR = 0.5
_NEWS_FRESHNESS_WINDOW_HOURS = 48.0
_NEWS_PRIMARY_ENTITY_MULT = 1.2
_NEWS_MENTIONED_ENTITY_MULT = 0.8
_VOLUME_LIQUIDITY_FLOOR = 100_000
_VOLUME_MAX_BOOST = 0.5

def score_claim(claim: Claim) -> float:
    score = _BASE_STRENGTH[claim["strength"]]
    if claim.get("corroborated"):
        score *= _CORROBORATION_BONUS
    if claim.get("flagged_unreliable"):
        score *= _UNRELIABLE_PENALTY
    if claim.get("rebutted_undefended"):
        score *= _REBUTTED_UNDEFENDED_PENALTY

    if claim.get("source_type") == "news":
        hours_old = claim.get("news_hours_old") or 0.0
        decay = max(_NEWS_FRESHNESS_FLOOR, min(1.0, 1.0 - hours_old / _NEWS_FRESHNESS_WINDOW_HOURS))
        score *= decay
        score *= _NEWS_PRIMARY_ENTITY_MULT if claim.get("news_is_primary_entity") else _NEWS_MENTIONED_ENTITY_MULT

    if claim.get("source_type") == "volume":
        avg_volume = claim.get("avg_volume") or 0.0
        if avg_volume >= _VOLUME_LIQUIDITY_FLOOR:
            ratio = claim.get("volume_ratio") or 1.0
            boost = min(_VOLUME_MAX_BOOST, math.log10(max(ratio, 1.0)))
            score *= 1.0 + boost

    return score


_RISK_CONFIDENCE_MULT = {"low": 1.0, "medium": 0.75, "high": 0.5}

def compute_verdict(bull_claims: list[Claim], bear_claims: list[Claim], risk_level: Literal["low", "medium", "high"]) -> Verdict:
    bull_total = sum(score_claim(c) for c in bull_claims)
    bear_total = sum(score_claim(c) for c in bear_claims)
    denom = bull_total + bear_total

    if denom == 0:
        return {"net_score": 0.0, "confidence": 0.0, "label": "Neutral, no confidence"}

    net_score = max(-100.0, min(100.0, 100.0 * (bull_total - bear_total) / denom))

    flagged_or_rebutted = sum(
        1 for c in bull_claims + bear_claims
        if c.get("flagged_unreliable") or c.get("rebutted_undefended")
    )
    corroborated = sum(1 for c in bull_claims + bear_claims if c.get("corroborated"))
    total_claims = len(bull_claims) + len(bear_claims)

    base_confidence = abs(net_score)
    # Scaled by share of claims rather than a flat per-claim count: a fixed 8/5 points per
    # claim saturates both caps at just 5-4 claims out of this pipeline's typical 24-32,
    # which made confidence land near 0% almost regardless of how one-sided the debate
    # actually was (a healthy debate normally produces several flagged/rebutted claims as a
    # byproduct of the rebuttal mechanic, not as a sign of unreliable data). Using each
    # claim's share of the total keeps the same intent -- more contested claims lower
    # confidence, more corroboration raises it -- without auto-maxing out on volume alone.
    penalty = min(40.0, (flagged_or_rebutted / total_claims) * 100.0)
    boost = min(20.0, (corroborated / total_claims) * 100.0)
    confidence = max(0.0, min(100.0, base_confidence - penalty + boost))
    confidence *= _RISK_CONFIDENCE_MULT[risk_level]

    direction = "Bullish" if net_score > 0 else "Bearish" if net_score < 0 else "Neutral"
    tier = "high" if confidence >= 70 else "moderate" if confidence >= 40 else "low"
    label = f"{direction}, {tier} confidence"

    return {"net_score": net_score, "confidence": confidence, "label": label}
