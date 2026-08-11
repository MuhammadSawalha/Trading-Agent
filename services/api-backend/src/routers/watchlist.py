from fastapi import APIRouter, HTTPException, Request
from common.dynamo import add_to_watchlist, remove_from_watchlist, read_watchlist, WatchlistFullError
from ..mcp_client import call_own_tool

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

@router.post("/{symbol}", status_code=201)
async def add_symbol(symbol: str, request: Request):
    profile = await call_own_tool(request.app.state.mcp_client, "finnhub_company_profile", symbol=symbol)
    if not profile:
        raise HTTPException(status_code=422, detail=f"'{symbol}' is not a recognized symbol")
    try:
        add_to_watchlist(symbol)
    except WatchlistFullError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"symbol": symbol}

@router.delete("/{symbol}", status_code=204)
async def remove_symbol(symbol: str):
    remove_from_watchlist(symbol)

@router.get("")
async def list_watchlist():
    return read_watchlist()
