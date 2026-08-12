#!/usr/bin/env bash
set -euo pipefail

echo "Waiting for services..."
# mcp-server is a FastMCP streamable_http_app: it only mounts /mcp, with no
# bare "/" or "/healthz" route, so a 2xx-requiring "curl -sf" against either
# would 404 forever. Any HTTP response (including 4xx/405/406) means the port
# is up, so drop -f here and just wait for curl to stop failing on connection
# refused/unreachable.
until curl -s -o /dev/null http://localhost:8001/mcp; do sleep 2; done
# api-backend genuinely serves a 2xx /healthz (see services/api-backend/src/app.py),
# on port 8080 per docker-compose.yaml -- port 8000 in this stack belongs to
# dynamodb-local, not api-backend.
until curl -sf http://localhost:8080/healthz >/dev/null; do sleep 2; done

echo "Adding AAPL to watchlist..."
# watchlist router is mounted with prefix /watchlist and no /api prefix
# (see services/api-backend/src/routers/watchlist.py and app.py).
curl -sf -X POST http://localhost:8080/watchlist/AAPL

echo "Waiting for the Scheduler's first tick to process it (up to 90s)..."
# Scheduler tick interval is 60s (services/scheduler/src/loop.py run_forever
# default), so 45 * 2s = 90s covers a full tick plus margin.
for i in $(seq 1 45); do
  # dashboard router has no prefix either (see services/api-backend/src/routers/dashboard.py);
  # the real path is /symbols/{symbol}/detail.
  DETAIL=$(curl -sf http://localhost:8080/symbols/AAPL/detail)
  if echo "$DETAIL" | grep -q '"Manager"'; then
    echo "Manager verdict present. Smoke test passed."
    exit 0
  fi
  sleep 2
done

echo "FAILED: no Manager verdict for AAPL after 90s"
exit 1
