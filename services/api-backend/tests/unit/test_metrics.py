from fastapi.testclient import TestClient
from src.app import create_app

def test_metrics_endpoint_returns_prometheus_exposition_format():
    client = TestClient(create_app())
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.content  # non-empty exposition body

def test_metrics_endpoint_reflects_instrumented_request_counts():
    client = TestClient(create_app())
    client.get("/healthz")
    response = client.get("/metrics")
    # prometheus-fastapi-instrumentator exposes per-route request counters; asserting
    # on the metric family name (rather than a specific label set) keeps this from
    # being coupled to the library's exact label/bucket layout.
    assert "http_requests_total" in response.text
