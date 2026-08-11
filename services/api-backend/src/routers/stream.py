import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from common.dynamo import query_process_history, read_watchlist, read_tool_result

router = APIRouter(tags=["stream"])
_POLL_INTERVAL_SECONDS = 1.5
_NEWS_POLL_INTERVAL_SECONDS = 1.5

async def _symbol_event_generator(symbol: str, max_polls: int | None):
    last_seen_sk = None
    polls = 0
    while max_polls is None or polls < max_polls:
        entries = query_process_history(symbol)
        new_entries = entries if last_seen_sk is None else [
            e for e in entries if e.get("timestamp", "") > last_seen_sk
        ]
        for entry in new_entries:
            yield f"data: {json.dumps(entry)}\n\n"
        if entries:
            last_seen_sk = entries[-1]["timestamp"]
        polls += 1
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

@router.get("/symbols/{symbol}/stream")
async def symbol_stream(symbol: str, _test_max_polls: int | None = None):
    return StreamingResponse(
        _symbol_event_generator(symbol, _test_max_polls),
        media_type="text/event-stream",
    )

async def _news_event_generator(max_polls: int | None):
    last_seen_uuids: dict[str, set[str]] = {}
    polls = 0
    while max_polls is None or polls < max_polls:
        for symbol in read_watchlist():
            result = read_tool_result(f"{symbol}#marketaux_news_all") or {}
            articles = result.get("data", [])
            seen = last_seen_uuids.setdefault(symbol, set())
            new_articles = [a for a in articles if a.get("uuid") not in seen]
            for article in new_articles:
                yield f"data: {json.dumps({'symbol': symbol, **article})}\n\n"
            seen.update(a["uuid"] for a in articles if a.get("uuid"))
        polls += 1
        await asyncio.sleep(_NEWS_POLL_INTERVAL_SECONDS)

@router.get("/stream/news")
async def news_stream(_test_max_polls: int | None = None):
    return StreamingResponse(
        _news_event_generator(_test_max_polls),
        media_type="text/event-stream",
    )
