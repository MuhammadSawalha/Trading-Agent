import functools
import logging
from typing import Literal
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState, SpecialistOutput
from common.dynamo import read_agent_output, write_agent_output, append_process_history
from common.tracing import langfuse_config
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Graph node / GraphState keys stay lowercase; the Dynamo AgentOutputs / ProcessHistory
# rows use the capitalized display name, matching "Manager"/"Bull"/"Bear"/"Risk" elsewhere.
_DISPLAY_NAMES = {
    "fundamentals": "Fundamentals",
    "technical": "Technical",
    "sentiment": "Sentiment",
    "macro_options": "Macro_Options",
}

class ClaimModel(BaseModel):
    strength: Literal["strong", "moderate", "weak"]
    corroborated: bool
    flagged_unreliable: bool
    # Bull/Bear (services/scheduler/src/graph/debate.py) always overwrite this themselves
    # right after parsing a claim, so it carries no information from the LLM — a default
    # keeps a model's inconsistent inclusion of it from failing validation outright.
    rebutted_undefended: bool = False
    source_type: Literal["news", "volume", "other"]
    rationale: str
    # Populated only for source_type="news" (Sentiment) / "volume" (Technical) claims — Task 3's
    # score_claim reads these for the freshness/centrality and log-compressed volume adjustments
    # (spec §4.5.1). None for every other claim; score_claim treats missing volume/news fields
    # as "no adjustment" rather than crashing.
    news_hours_old: float | None = None
    news_is_primary_entity: bool | None = None
    volume_ratio: float | None = None
    avg_volume: float | None = None

class SpecialistResponse(BaseModel):
    claims: list[ClaimModel]

@functools.lru_cache(maxsize=1)
def _get_llm():
    return ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-east-1",
    ).with_structured_output(SpecialistResponse)

def _invoke_llm(system_prompt: str, tool_data: dict, symbol: str) -> dict:
    llm = _get_llm()
    response = llm.invoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Data:\n{tool_data}"},
        ],
        config=langfuse_config(session_id=symbol, tags=[system_prompt[:20]]),
    )
    return response.model_dump()

FUNDAMENTALS_PROMPT = (
    "You are the Fundamentals specialist. Interpret the provided financial-statement, "
    "ratio, valuation, and insider-activity data into structured claims. Output only "
    "claims directly supported by the data, each with strength, corroboration, and a "
    "short rationale. Never speculate beyond what the data shows."
)
TECHNICAL_PROMPT = (
    "You are the Technical specialist. Interpret the provided price, volume, and "
    "technical-indicator data into structured claims about trend and momentum. Output "
    "only claims directly supported by the data. For any claim grounded in an unusual-volume "
    "reading, set source_type to 'volume' and populate volume_ratio (today's volume / average "
    "volume) and avg_volume from the data — leave both null for claims not about volume."
)
SENTIMENT_PROMPT = (
    "You are the Sentiment specialist. Interpret the provided news articles into "
    "structured claims about market sentiment. Weight claims by how central the company "
    "is to each article and by recency. For every claim, set source_type to 'news' and "
    "populate news_hours_old (hours since the article's published_at) and "
    "news_is_primary_entity (true if the company is the article's main subject, false if "
    "only mentioned) from the article metadata in the data."
)
MACRO_OPTIONS_PROMPT = (
    "You are the Macro/Options specialist. Interpret the provided macroeconomic "
    "indicators and options-market data (chain skew, unusual activity) into structured "
    "claims about the macro backdrop and options-implied sentiment for this symbol."
)

_MAX_ATTEMPTS = 3

def make_specialist_node(name: str, system_prompt: str):
    display_name = _DISPLAY_NAMES[name]

    def node(state: GraphState) -> dict:
        symbol = state["symbol"]
        if not state.get("is_new_symbol") and name not in state.get("changed_specialists", set()):
            cached = read_agent_output(symbol, display_name)
            if cached is not None:
                return {name: cached}

        append_process_history(symbol, display_name, reason="pipeline_run", status="started", timestamp=datetime.now(timezone.utc))
        # with_structured_output occasionally has the model return a field in a form that
        # fails Pydantic validation outright (e.g. `claims` serialized as a JSON string
        # instead of an actual list) rather than a substantively wrong-but-valid answer --
        # a transient tool-calling format slip, not a real disagreement to reason about. A
        # bounded retry recovers from that immediately; without one, this node's failure
        # aborts the whole pipeline run for the symbol this tick, and the next opportunity to
        # retry all the way down here depends on some *other* specialist's input data
        # happening to change again. One terminal "started"/"failed" pair covers the whole
        # attempt loop, not one pair per attempt.
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                output: SpecialistOutput = _invoke_llm(system_prompt, state.get("tool_data", {}).get(name, {}), symbol)
                write_agent_output(symbol, display_name, output)
                append_process_history(symbol, display_name, reason="pipeline_run", status="finished", timestamp=datetime.now(timezone.utc))
                return {name: output}
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "specialist %s failed for %s on attempt %d/%d, %s",
                    display_name, symbol, attempt, _MAX_ATTEMPTS,
                    "retrying" if attempt < _MAX_ATTEMPTS else "giving up",
                    exc_info=True,
                )

        append_process_history(symbol, display_name, reason="pipeline_run", status="failed", timestamp=datetime.now(timezone.utc))
        raise last_error

    node.__name__ = name
    return node
