import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from fastapi.concurrency import run_in_threadpool
from langchain_aws import ChatBedrockConverse
from common.tracing import langfuse_config
from ..chat.grounding import build_context
from ..mcp_client import call_own_tool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])
_TIMING_KEYWORDS = ["when", "last updated", "why did", "history", "changed"]

class ChatRequest(BaseModel):
    # Bounded because /chat is unauthenticated and build_context does
    # len(symbols) x 8 sequential blocking reads: without a cap a single
    # request is a cheap resource-exhaustion lever. 30 matches the
    # watchlist's own maximum size.
    question: str = Field(max_length=2000)
    symbols: list[str] = Field(max_length=30)

def _invoke_chat_llm(question: str, context: str, history_context: str, session_id: str) -> str:
    llm = ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-east-1",
    )
    system_prompt = (
        "You are a research assistant grounded strictly in the cached analysis below. "
        "Never present the composite score as investment advice or a validated trading "
        "signal — it is research output only. Match your reply's length and content to "
        "what was actually asked: respond to greetings and small talk briefly and "
        "naturally, without summarizing the data. Only draw on the cached analysis, and "
        "only as much of it, as the question calls for — don't volunteer a full research "
        "dump unless the user actually asks for an overview."
    )
    response = llm.invoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{context}\n\n{history_context}\n\nQuestion: {question}"},
        ],
        config=langfuse_config(session_id=session_id, tags=[system_prompt[:20]]),
    )
    return response.content

@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    context = build_context(body.symbols)
    history_context = ""
    if any(kw in body.question.lower() for kw in _TIMING_KEYWORDS) and body.symbols:
        try:
            history = await call_own_tool(request.app.state.mcp_client, "query_process_history_tool", symbol=body.symbols[0])
            history_context = f"Process history for {body.symbols[0]}:\n{history}"
        except Exception:
            logger.warning(
                "query_process_history_tool call failed for symbol %s; "
                "falling back to context-only answer",
                body.symbols[0],
                exc_info=True,
            )
    # _invoke_chat_llm blocks on the full Bedrock round-trip (seconds). Called
    # directly from this async handler it would stall uvicorn's single event
    # loop, freezing every other request and SSE stream on this pod.
    # /chat is stateless per-request (ChatRequest carries no conversation/session id), so
    # the requested symbol set stands in for a Langfuse session -- chat calls about the
    # same symbols group together in the dashboard; falls back to a fixed session for
    # symbol-less questions.
    session_id = ",".join(body.symbols) if body.symbols else "chat-general"
    answer = await run_in_threadpool(_invoke_chat_llm, body.question, context, history_context, session_id)
    return {"answer": answer}
