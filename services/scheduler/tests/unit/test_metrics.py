import http.client
import threading
from src.main import HealthHandler, _build_health_server

# Task 54: the scheduler has no ASGI app (its health server is a plain http.server), so
# /metrics is a second route on the same HealthHandler as /healthz -- exercised here the
# same way test_main.py exercises /healthz, over a real socket against a running
# ThreadingHTTPServer.


def test_metrics_endpoint_returns_prometheus_exposition_format():
    server = _build_health_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/metrics")
        response = conn.getresponse()
        body = response.read()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("text/plain")
        assert body  # non-empty exposition body
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_metrics_endpoint_includes_default_process_collector_output():
    server = _build_health_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/metrics")
        response = conn.getresponse()
        body = response.read().decode()
        # prometheus_client auto-registers a ProcessCollector against the default
        # registry on import, so this metric family is present with zero extra wiring.
        assert "process_cpu_seconds_total" in body
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_unknown_paths_still_404():
    server = _build_health_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/nope")
        response = conn.getresponse()
        assert response.status == 404
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
