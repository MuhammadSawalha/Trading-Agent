import asyncio
import json
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from common.dynamo import query_process_history, read_watchlist, read_tool_result

router = APIRouter(tags=["stream"])
_POLL_INTERVAL_SECONDS = 1.5
_NEWS_POLL_INTERVAL_SECONDS = 1.5

# Emitted when a poll cycle produces no new events. Without it an idle
# connection (potentially minutes between pipeline runs) sends no bytes at all
# and can be dropped by an intermediate proxy/load-balancer idle timeout.
_KEEPALIVE_FRAME = ": keepalive\n\n"

async def _symbol_event_generator(symbol: str, max_polls: int | None):
    last_seen_timestamp = None
    polls = 0
    while max_polls is None or polls < max_polls:
        # query_process_history is a synchronous, blocking boto3 call. Called
        # directly it would block uvicorn's single event-loop thread on every
        # poll for the whole lifetime of every connected client, stalling all
        # other in-flight requests and streams on this pod.
        #
        # Passing `since` lets DynamoDB itself bound the read to entries at-or-after
        # the last-seen timestamp instead of re-fetching the symbol's entire history
        # on every 1.5s poll for the connection's whole lifetime. The `since` bound is
        # inclusive, so the last-seen entry itself is expected to come back; the
        # `new_entries` filter below is what excludes it from being re-emitted.
        since = datetime.fromisoformat(last_seen_timestamp) if last_seen_timestamp else None
        entries = await asyncio.to_thread(query_process_history, symbol, since=since)
        new_entries = entries if last_seen_timestamp is None else [
            e for e in entries if e.get("timestamp", "") > last_seen_timestamp
        ]
        for entry in new_entries:
            # The `id:` field gives clients standard SSE reconnect support via
            # the Last-Event-ID header. `sk` is written by append_process_history
            # alongside `timestamp`, so it is the natural per-entry cursor.
            yield f"id: {entry['sk']}\ndata: {json.dumps(entry)}\n\n"
        if not new_entries:
            yield _KEEPALIVE_FRAME
        if entries:
            last_seen_timestamp = entries[-1]["timestamp"]
        polls += 1
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

@router.get("/symbols/{symbol}/stream")
async def symbol_stream(symbol: str, _test_max_polls: int | None = None):
    return StreamingResponse(
        _symbol_event_generator(symbol, _test_max_polls),
        media_type="text/event-stream",
    )

# Marketaux tags an article for a symbol whenever that company is *mentioned* anywhere in the
# body (a "top 10 holdings" roundup, an unrelated multi-company piece, ...), not only when the
# article is actually about it -- the fetch itself is already restricted to language=en
# (input_data_agent.py), but older cached articles fetched before that filter existed, plus
# this "mentioned vs. about" gap, both still need handling here for what the news panel shows.
#
# Requiring the company's name to appear in the title was tried first and rejected: real
# headlines routinely lead with a product/brand instead of the legal entity ("Azure ..." for
# Microsoft, "Waymo ..." for Alphabet), so it excluded genuinely single-subject articles as
# often as it excluded true multi-company roundups. What actually separates the two in
# marketaux's own data is how many distinct companies got tagged at all: an article about one
# company overwhelmingly tags just that one equity, while a "top holdings"/"AI giants" roundup
# tags a handful to dozens. So an article is relevant if it's essentially single-subject
# (at most one other tagged equity, to allow for a natural head-to-head comparison piece) OR
# the company's name/a known brand alias is spelled out in the title regardless of entity count.
_COMPANY_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "GOOG": ("Google",), "GOOGL": ("Google",), "META": ("Facebook",),
}
_CORPORATE_SUFFIXES = (
    " Corporation", " Corp.", " Corp", " Incorporated", " Inc.", " Inc",
    " Co.", " Ltd.", " Ltd", " PLC", " plc", " Holdings", " Group",
)
_MAX_CO_TAGGED_EQUITIES = 2

def _entity_display_names(symbol: str, article: dict) -> list[str]:
    names = [symbol, *_COMPANY_NAME_ALIASES.get(symbol, ())]
    entity = next((e for e in article.get("entities", []) if e.get("symbol") == symbol), None)
    if entity and entity.get("name"):
        name = entity["name"]
        for suffix in _CORPORATE_SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        names.append(name)
    return names

def _is_relevant_article(symbol: str, article: dict) -> bool:
    if article.get("language") != "en":
        return False
    equity_symbols = {e.get("symbol") for e in article.get("entities", []) if e.get("type") == "equity"}
    if len(equity_symbols) <= _MAX_CO_TAGGED_EQUITIES:
        return True
    title = (article.get("title") or "").lower()
    return any(name.lower() in title for name in _entity_display_names(symbol, article) if name)

def _poll_news_once(last_seen_uuids: dict[str, set[str]]) -> list[dict]:
    """One full synchronous news poll: watchlist read + a per-symbol tool-result
    read + dedup-set update, returning the new, relevant articles tagged by symbol.

    Kept as a single sync function so a whole poll cycle -- up to 31 sequential
    blocking DynamoDB calls -- costs one thread hop instead of 31.
    """
    new_events = []
    for symbol in read_watchlist():
        result = read_tool_result(f"{symbol}#marketaux_news_all") or {}
        articles = [a for a in result.get("data", []) if _is_relevant_article(symbol, a)]
        seen = last_seen_uuids.setdefault(symbol, set())
        new_events.extend(
            {"symbol": symbol, **a} for a in articles if a.get("uuid") not in seen
        )
        seen.update(a["uuid"] for a in articles if a.get("uuid"))
    return new_events

async def _news_event_generator(max_polls: int | None):
    last_seen_uuids: dict[str, set[str]] = {}
    polls = 0
    while max_polls is None or polls < max_polls:
        new_events = await asyncio.to_thread(_poll_news_once, last_seen_uuids)
        for event in new_events:
            yield f"data: {json.dumps(event)}\n\n"
        if not new_events:
            yield _KEEPALIVE_FRAME
        polls += 1
        await asyncio.sleep(_NEWS_POLL_INTERVAL_SECONDS)

@router.get("/stream/news")
async def news_stream(_test_max_polls: int | None = None):
    return StreamingResponse(
        _news_event_generator(_test_max_polls),
        media_type="text/event-stream",
    )
