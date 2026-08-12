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
  # symbol_detail() (services/api-backend/src/routers/dashboard.py) unconditionally writes an
  # "agents.manager" entry for every symbol, even before any pipeline has run -- it falls back
  # to `read_agent_output(...) or {}`, so a plain `grep -q '"Manager"'` would pass on the very
  # first poll regardless of whether a real verdict exists. What only appears once the Manager
  # agent has actually written output is a non-null agents.manager.last_updated (populated from
  # ProcessHistory), so check that instead of just the key's presence.
  if echo "$DETAIL" | python3 -c "
import json, sys
data = json.load(sys.stdin)
sys.exit(0 if data.get('agents', {}).get('manager', {}).get('last_updated') else 1)
"; then
    echo "Manager verdict present. Smoke test passed."
    exit 0
  fi
  sleep 2
done

echo "FAILED: no Manager verdict for AAPL after 90s"
exit 1
