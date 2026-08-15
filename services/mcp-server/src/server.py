from mcp.server.fastmcp import FastMCP
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.requests import Request
from starlette.responses import Response


def create_app() -> FastMCP:
    # Binds to 0.0.0.0:8001 (rather than FastMCP's 127.0.0.1:8000 default) to
    # match the Dockerfile's EXPOSE 8001 and docker-compose's port mapping /
    # MCP_SERVER_URL, and to be reachable from sibling containers rather than
    # only from localhost inside this container.
    app = FastMCP("stock-research-mcp-server", host="0.0.0.0", port=8001)

    # httpx request-logging (which would log full URLs, including the
    # provider API key ProviderClient.get() puts in the query string) is
    # suppressed at import time in src/clients/base.py, which every provider
    # client (and therefore this app) imports.

    from .tools.finnhub_tools import register_finnhub_tools
    from .tools.fmp_tools import register_fmp_tools
    from .tools.fred_tools import register_fred_tools
    from .tools.marketaux_tools import register_marketaux_tools
    from .tools.scoring_tool import register_scoring_tool
    from .tools.process_history_tool import register_process_history_tool

    register_finnhub_tools(app)
    register_fmp_tools(app)
    register_fred_tools(app)
    register_marketaux_tools(app)
    register_scoring_tool(app)
    register_process_history_tool(app)

    # Exposes GET /metrics in Prometheus exposition format for the ServiceMonitor in
    # monitoring/prometheus/servicemonitors.yaml to scrape.
    #
    # `prometheus-fastapi-instrumentator` (used for api-backend) isn't an option here:
    # it's built around FastAPI's route/OpenAPI introspection, but
    # `FastMCP.streamable_http_app()` / `.run(transport="streamable-http")` build and
    # serve a bare Starlette app, not a FastAPI one. `FastMCP.run()` also has no hook to
    # inject ASGI middleware or a sub-mounted app before it hands the Starlette app to
    # uvicorn, so a manually-mounted `prometheus_client.make_asgi_app()` (or a
    # `starlette_exporter` middleware) would require bypassing `.run()` entirely and
    # reimplementing its uvicorn-serving logic.
    #
    # `custom_route` is FastMCP's own public extension point for adding plain HTTP
    # routes (its docstring calls out health checks as the canonical example) to the
    # Starlette app it builds internally, so it's used here to register /metrics without
    # touching how the app is run. It returns `generate_latest()` against the default
    # `prometheus_client` registry, which — via that library's auto-registered
    # ProcessCollector/PlatformCollector/GCCollector — is a non-empty, valid exposition
    # payload with no extra wiring. Per-request counters/histograms (analogous to what
    # prometheus-fastapi-instrumentator gives api-backend for free) are not added here;
    # they're in scope for a later task, not this one.
    @app.custom_route("/metrics", methods=["GET"])
    async def metrics(_request: Request) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # infra/k8s/helm/mcp-server's liveness/readiness probes hit GET /healthz on this same
    # port; without this route they 404 and Kubernetes kills the container in a crash loop.
    @app.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> Response:
        return Response(status_code=200)

    return app


if __name__ == "__main__":
    create_app().run(transport="streamable-http")
