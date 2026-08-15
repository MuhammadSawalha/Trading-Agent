import pytest
from starlette.testclient import TestClient
from src.server import create_app

# Task 54: mcp-server runs on FastMCP's Starlette app (not FastAPI), so its /metrics
# endpoint is exercised over a real ASGI transport via Starlette's own TestClient --
# mirroring test_mcp_transport.py's use of a real transport rather than calling
# create_app()'s internals directly.


@pytest.fixture
def http_client(monkeypatch):
    for var in ["FINNHUB_API_KEY", "FMP_API_KEY", "FRED_API_KEY", "MARKETAUX_API_KEY"]:
        monkeypatch.setenv(var, "test-key")
    app = create_app()
    starlette_app = app.streamable_http_app()
    with TestClient(starlette_app) as client:
        yield client


def test_metrics_endpoint_returns_prometheus_exposition_format(http_client):
    response = http_client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.content  # non-empty exposition body


def test_metrics_endpoint_includes_default_process_collector_output(http_client):
    response = http_client.get("/metrics")
    # prometheus_client auto-registers a ProcessCollector against the default registry
    # on import, so this metric family is present with zero extra wiring.
    assert "process_cpu_seconds_total" in response.text
