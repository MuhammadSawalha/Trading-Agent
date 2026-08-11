import asyncio
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .heartbeat import is_healthy
from .loop import run_forever
from .mcp_clients import build_mcp_client

_MAX_STALENESS_SECONDS = 180  # 3x the 60s tick interval

class HealthHandler(BaseHTTPRequestHandler):
    # socketserver.StreamRequestHandler.setup() applies this as a socket timeout, so a client
    # that opens a connection and never completes a request line gets dropped after this many
    # seconds instead of holding the connection (and, pre-Finding-3, the whole single-threaded
    # server) open forever. The Scheduler is a deliberate single-replica SPOF (spec forbids
    # HPA-scaling it), so there's no sibling replica to cover for a wedged health server.
    timeout = 5

    def do_GET(self):
        if self.path != "/healthz":
            self.send_response(404)
            self.end_headers()
            return
        healthy = is_healthy(datetime.now(timezone.utc), _MAX_STALENESS_SECONDS)
        self.send_response(200 if healthy else 503)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # keep container logs to the scheduler's own logging, not the health server's

def _build_health_server(host: str = "0.0.0.0", port: int = 8002) -> ThreadingHTTPServer:
    # ThreadingHTTPServer (rather than plain HTTPServer) so one slow/hung client's connection
    # is handled on its own thread and can't block other /healthz probes from being served.
    return ThreadingHTTPServer((host, port), HealthHandler)

def _run_health_server():
    _build_health_server().serve_forever()

async def main() -> None:
    threading.Thread(target=_run_health_server, daemon=True).start()
    client = build_mcp_client()
    await run_forever(client)

if __name__ == "__main__":
    asyncio.run(main())
