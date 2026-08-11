import asyncio
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from .heartbeat import is_healthy
from .loop import run_forever
from .mcp_clients import build_mcp_client

_MAX_STALENESS_SECONDS = 180  # 3x the 60s tick interval

class HealthHandler(BaseHTTPRequestHandler):
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

def _run_health_server():
    HTTPServer(("0.0.0.0", 8002), HealthHandler).serve_forever()

async def main() -> None:
    threading.Thread(target=_run_health_server, daemon=True).start()
    client = build_mcp_client()
    await run_forever(client)

if __name__ == "__main__":
    asyncio.run(main())
