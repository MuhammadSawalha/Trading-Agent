from fastapi import FastAPI
from .routers.watchlist import router as watchlist_router
from .mcp_client import build_own_mcp_client

def create_app() -> FastAPI:
    app = FastAPI(title="Stock Research Agent API")
    app.state.mcp_client = build_own_mcp_client()

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    app.include_router(watchlist_router)
    return app
