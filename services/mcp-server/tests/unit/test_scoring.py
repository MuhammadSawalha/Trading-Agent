from src.tools.scoring import score_claim, compute_verdict

def test_base_strength_values():
    strong = score_claim({"strength": "strong", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    moderate = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    weak = score_claim({"strength": "weak", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    assert strong == 3.0
    assert moderate == 2.0
    assert weak == 1.0

def test_corroboration_bonus_multiplies_by_1_5():
    base = score_claim({"strength": "strong", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    corroborated = score_claim({"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    assert corroborated == base * 1.5

def test_unreliable_data_penalty_halves_score():
    base = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    flagged = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": True, "rebutted_undefended": False, "source_type": "other"})
    assert flagged == base * 0.5

def test_rebutted_undefended_penalty_quarters_score():
    base = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    rebutted = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": True, "source_type": "other"})
    assert rebutted == base * 0.25

def test_penalties_and_bonus_compose_multiplicatively():
    claim = {"strength": "strong", "corroborated": True, "flagged_unreliable": True, "rebutted_undefended": False, "source_type": "other"}
    assert score_claim(claim) == 3.0 * 1.5 * 0.5

def test_news_freshness_decays_over_48_hours():
    fresh = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": 0, "news_is_primary_entity": True})
    stale = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": 48, "news_is_primary_entity": True})
    assert fresh > stale
    assert stale == 2.0 * 0.5 * 1.2  # floor multiplier 0.5, primary-entity multiplier 1.2

def test_news_non_primary_entity_discounted():
    primary = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": 0, "news_is_primary_entity": True})
    mentioned = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": 0, "news_is_primary_entity": False})
    assert mentioned == primary / 1.2 * 0.8

def test_volume_extremity_is_log_compressed_and_liquidity_gated():
    liquid = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "volume", "volume_ratio": 10.0, "avg_volume": 5_000_000})
    illiquid = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "volume", "volume_ratio": 10.0, "avg_volume": 10_000})
    assert liquid > 2.0  # boosted
    assert illiquid == 2.0  # liquidity gate: below 100k avg volume, no boost applied

def _claim(strength="moderate", **overrides):
    base = {"strength": strength, "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"}
    base.update(overrides)
    return base

def test_net_score_positive_when_bull_dominates():
    verdict = compute_verdict(bull_claims=[_claim("strong"), _claim("strong")], bear_claims=[_claim("weak")], risk_level="low")
    assert verdict["net_score"] > 0

def test_net_score_negative_when_bear_dominates():
    verdict = compute_verdict(bull_claims=[_claim("weak")], bear_claims=[_claim("strong"), _claim("strong")], risk_level="low")
    assert verdict["net_score"] < 0

def test_net_score_zero_with_no_claims():
    verdict = compute_verdict(bull_claims=[], bear_claims=[], risk_level="low")
    assert verdict["net_score"] == 0.0
    assert verdict["confidence"] == 0.0

def test_net_score_bounded_at_100():
    verdict = compute_verdict(bull_claims=[_claim("strong")] * 10, bear_claims=[], risk_level="low")
    assert verdict["net_score"] == 100.0

def test_risk_adjustment_scales_confidence_never_flips_direction():
    low = compute_verdict(bull_claims=[_claim("strong"), _claim("strong")], bear_claims=[_claim("weak")], risk_level="low")
    high = compute_verdict(bull_claims=[_claim("strong"), _claim("strong")], bear_claims=[_claim("weak")], risk_level="high")
    assert low["confidence"] > high["confidence"]
    assert (low["net_score"] > 0) == (high["net_score"] > 0)

def test_label_reflects_direction_and_confidence():
    verdict = compute_verdict(bull_claims=[_claim("strong"), _claim("strong"), _claim("strong")], bear_claims=[], risk_level="low")
    assert verdict["label"].startswith("Bullish")

    verdict = compute_verdict(bull_claims=[], bear_claims=[_claim("strong"), _claim("strong"), _claim("strong")], risk_level="low")
    assert verdict["label"].startswith("Bearish")
