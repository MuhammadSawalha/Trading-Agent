from fastapi import FastAPI
from .routers.watchlist import router as watchlist_router
from .routers.dashboard import router as dashboard_router
from .routers.stream import router as stream_router
from .routers.chat import router as chat_router
from .mcp_client import build_own_mcp_client

def create_app() -> FastAPI:
    app = FastAPI(title="Stock Research Agent API")
    app.state.mcp_client = build_own_mcp_client()

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    app.include_router(watchlist_router)
    app.include_router(dashboard_router)
    app.include_router(stream_router)
    app.include_router(chat_router)
    return app
