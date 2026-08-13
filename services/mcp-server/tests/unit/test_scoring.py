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

def test_news_freshness_decay_is_capped_at_1_for_future_dated_news():
    now = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": 0, "news_is_primary_entity": True})
    future = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": -10, "news_is_primary_entity": True})
    assert future <= now

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

def test_penalty_and_boost_scale_with_claim_share_not_raw_count():
    # A flat per-claim penalty/boost saturates at just 5 flagged/rebutted or 4 corroborated
    # claims regardless of how many claims exist overall -- on a debate with ~15 claims per
    # side (this pipeline's normal volume), that meant confidence landed near 0% almost every
    # time, since a healthy debate routinely produces that many flagged/rebutted claims as a
    # byproduct of the rebuttal mechanic, not as a sign of unreliable data. Scaling by each
    # claim's share of the total keeps a heavily-contested case penalized while not
    # auto-maxing out on claim volume alone.
    strong_uncontested = lambda: {
        "strength": "strong", "corroborated": True, "flagged_unreliable": False,
        "rebutted_undefended": False, "source_type": "other",
    }
    flagged = lambda: {
        "strength": "strong", "corroborated": False, "flagged_unreliable": True,
        "rebutted_undefended": False, "source_type": "other",
    }
    # 20 claims total, only 2 flagged (10%) -- well below the old formula's 5-claim saturation
    # point, so confidence should reflect the mostly-clean, mostly-corroborated debate rather
    # than being wiped out to 0.
    verdict = compute_verdict(
        bull_claims=[strong_uncontested() for _ in range(18)] + [flagged()],
        bear_claims=[flagged()],
        risk_level="low",
    )
    assert verdict["confidence"] > 50.0
