from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState, SpecialistOutput
from common.dynamo import read_agent_output, write_agent_output, append_process_history
from datetime import datetime, timezone

class ClaimModel(BaseModel):
    strength: str
    corroborated: bool
    flagged_unreliable: bool
    rebutted_undefended: bool
    source_type: str
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

def _invoke_llm(system_prompt: str, tool_data: dict) -> dict:
    llm = ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-east-1",
    ).with_structured_output(SpecialistResponse)
    response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Data:\n{tool_data}"},
    ])
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

def make_specialist_node(name: str, system_prompt: str):
    def node(state: GraphState) -> dict:
        symbol = state["symbol"]
        if not state.get("is_new_symbol") and name not in state.get("changed_specialists", set()):
            cached = read_agent_output(symbol, name)
            if cached is not None:
                return {name: cached}

        append_process_history(symbol, name, reason="pipeline_run", status="started", timestamp=datetime.now(timezone.utc))
        output: SpecialistOutput = _invoke_llm(system_prompt, state.get("tool_data", {}).get(name, {}))
        write_agent_output(symbol, name, output)
        append_process_history(symbol, name, reason="pipeline_run", status="finished", timestamp=datetime.now(timezone.utc))
        return {name: output}

    node.__name__ = name
    return node
