from unittest.mock import patch
from src.graph.debate import bull_node, bear_node

def _all_specialist_claims():
    return {"claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "r"}]}

@patch("src.graph.debate._invoke_bull_llm")
def test_bull_node_collects_claims_from_all_specialists(mock_invoke):
    mock_invoke.return_value = [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}]
    state = {"symbol": "AAPL", "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
             "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims()}
    result = bull_node(state)
    assert len(result["bull_claims"]) == 1

@patch("src.graph.debate._invoke_bear_rebuttal_llm")
@patch("src.graph.debate._invoke_bear_llm")
def test_bear_node_marks_undefended_rebuttals_on_bull_claims(mock_bear, mock_rebuttal):
    mock_bear.return_value = [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bear case"}]
    mock_rebuttal.return_value = {"rebutted_claim_indices": [0], "succeeded_indices": [0]}
    state = {
        "symbol": "AAPL",
        "bull_claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}],
        "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
        "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims(),
    }
    result = bear_node(state)
    assert result["bull_claims"][0]["rebutted_undefended"] is True
    assert len(result["bear_claims"]) == 1
