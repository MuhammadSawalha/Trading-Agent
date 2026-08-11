from mcp.server.fastmcp import FastMCP
from .scoring import compute_verdict

def register_scoring_tool(app: FastMCP) -> None:
    @app.tool()
    async def score_verdict(bull_claims: list[dict], bear_claims: list[dict], risk_level: str) -> dict:
        """Compute the deterministic bull/bear/risk verdict (net score, confidence, label) from structured claims."""
        return compute_verdict(bull_claims, bear_claims, risk_level)  # type: ignore[arg-type]
