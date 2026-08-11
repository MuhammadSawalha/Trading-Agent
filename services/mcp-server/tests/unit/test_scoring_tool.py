import pytest
from mcp.server.fastmcp import FastMCP
from src.tools.scoring_tool import register_scoring_tool

@pytest.mark.asyncio
async def test_score_verdict_tool_delegates_to_compute_verdict():
    app = FastMCP("test")
    register_scoring_tool(app)
    tools = await app.list_tools()
    assert any(t.name == "score_verdict" for t in tools)

    result = await app.call_tool("score_verdict", {
        "bull_claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"}],
        "bear_claims": [],
        "risk_level": "low",
    })
    payload = result[0] if isinstance(result, tuple) else result
    assert payload  # non-empty verdict returned
