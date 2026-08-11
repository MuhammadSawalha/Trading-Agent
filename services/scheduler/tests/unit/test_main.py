import http.client
import socket
import threading
from datetime import datetime, timezone
import pytest
from src.main import HealthHandler, _build_health_server
from src.heartbeat import record_heartbeat

# Final review Finding 3: main.py previously used a plain (single-threaded, no request
# timeout) HTTPServer for the health endpoint. One client that opens a TCP connection and
# never completes a request line would block serve_forever() indefinitely, wedging every
# subsequent /healthz probe -- dangerous specifically because the Scheduler is a deliberate
# single-replica SPOF (spec forbids HPA-scaling it), so there's no sibling replica to cover
# for a wedged health server. The fix: ThreadingHTTPServer (so one slow connection doesn't
# block others) plus a bounded per-connection socket timeout (so a hung connection is
# eventually dropped rather than held forever).


def test_health_handler_has_a_bounded_timeout():
    # socketserver.StreamRequestHandler (which BaseHTTPRequestHandler subclasses) applies
    # this class attribute as a socket timeout in setup() -- None means "no timeout", which
    # is exactly the wedge-prone behavior being fixed here.
    assert HealthHandler.timeout is not None
    assert 0 < HealthHandler.timeout <= 30


def test_build_health_server_returns_a_threading_server():
    from http.server import ThreadingHTTPServer

    server = _build_health_server(host="127.0.0.1", port=0)
    try:
        assert isinstance(server, ThreadingHTTPServer)
    finally:
        server.server_close()


def test_hung_connection_does_not_block_other_clients_and_is_eventually_dropped():
    record_heartbeat(datetime.now(timezone.utc))
    server = _build_health_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # A client that connects but never sends a complete request line -- the scenario
        # that would wedge a single-threaded, timeout-less HTTPServer forever.
        hung_sock = socket.create_connection((host, port), timeout=5)

        # A second, well-behaved client must still be served promptly -- proves the hung
        # connection above isn't monopolizing the (single-threaded, in the old code)
        # server loop.
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/healthz")
        response = conn.getresponse()
        assert response.status == 200
        conn.close()

        # The hung connection must eventually be dropped by the handler's own socket
        # timeout rather than sit open forever. Give it timeout + a margin, then expect
        # the server to have closed its end (recv returns b'').
        hung_sock.settimeout(HealthHandler.timeout + 5)
        data = hung_sock.recv(1024)
        assert data == b""
        hung_sock.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
