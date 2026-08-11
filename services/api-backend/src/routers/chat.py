from fastapi import APIRouter, Request
from pydantic import BaseModel
from langchain_aws import ChatBedrockConverse
from ..chat.grounding import build_context
from ..mcp_client import call_own_tool

router = APIRouter(tags=["chat"])
_TIMING_KEYWORDS = ["when", "last updated", "why did", "history", "changed"]

class ChatRequest(BaseModel):
    question: str
    symbols: list[str]

def _invoke_chat_llm(question: str, context: str, history_context: str) -> str:
    llm = ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-east-1",
    )
    response = llm.invoke([
        {"role": "system", "content": (
            "You are a research assistant grounded strictly in the cached analysis below. "
            "Never present the composite score as investment advice or a validated trading "
            "signal — it is research output only."
        )},
        {"role": "user", "content": f"Context:\n{context}\n\n{history_context}\n\nQuestion: {question}"},
    ])
    return response.content

@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    context = build_context(body.symbols)
    history_context = ""
    if any(kw in body.question.lower() for kw in _TIMING_KEYWORDS) and body.symbols:
        history = await call_own_tool(request.app.state.mcp_client, "query_process_history_tool", symbol=body.symbols[0])
        history_context = f"Process history for {body.symbols[0]}:\n{history}"
    answer = _invoke_chat_llm(body.question, context, history_context)
    return {"answer": answer}
