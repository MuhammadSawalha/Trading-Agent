#!/usr/bin/env bash
set -euo pipefail

echo "Waiting for services..."
# mcp-server is a FastMCP streamable_http_app: it only mounts /mcp, with no
# bare "/" or "/healthz" route, so a 2xx-requiring "curl -sf" against either
# would 404 forever. Any HTTP response (including 4xx/405/406) means the port
# is up, so drop -f here and just wait for curl to stop failing on connection
# refused/unreachable. Bounded to 90s so a crashlooping container fails fast
# with a diagnostic instead of hanging forever.
mcp_up=0
for i in $(seq 1 45); do
  if curl -s -o /dev/null http://localhost:8001/mcp; then
    mcp_up=1
    break
  fi
  sleep 2
done
if [ "$mcp_up" -ne 1 ]; then
  echo "FAILED: mcp-server never came up on http://localhost:8001/mcp after 90s"
  exit 1
fi

# api-backend genuinely serves a 2xx /healthz (see services/api-backend/src/app.py),
# on port 8080 per docker-compose.yaml -- port 8000 in this stack belongs to
# dynamodb-local, not api-backend. Also bounded to 90s for the same reason.
api_up=0
for i in $(seq 1 45); do
  if curl -sf http://localhost:8080/healthz >/dev/null; then
    api_up=1
    break
  fi
  sleep 2
done
if [ "$api_up" -ne 1 ]; then
  echo "FAILED: api-backend never came up on http://localhost:8080/healthz after 90s"
  exit 1
fi

echo "Adding AAPL to watchlist..."
# watchlist router is mounted with prefix /watchlist and no /api prefix
# (see services/api-backend/src/routers/watchlist.py and app.py).
curl -sf -X POST http://localhost:8080/watchlist/AAPL

echo "Waiting for the Scheduler's first tick to process it (up to 90s)..."
# Scheduler tick interval is 60s (services/scheduler/src/loop.py run_forever
# default), so 45 * 2s = 90s covers a full tick plus margin.
for i in $(seq 1 45); do
  # dashboard router has no prefix either (see services/api-backend/src/routers/dashboard.py);
  # the real path is /symbols/{symbol}/detail. A single transient poll failure (non-2xx,
  # connection blip) must not kill the whole script under `set -e` -- fall through to the
  # next retry within the 90s budget instead.
  DETAIL=$(curl -sf http://localhost:8080/symbols/AAPL/detail) || { sleep 2; continue; }
  # symbol_detail() (services/api-backend/src/routers/dashboard.py) unconditionally writes an
  # "agents.manager" entry for every symbol, even before any pipeline has run -- it falls back
  # to `read_agent_output(...) or {}`, so a plain `grep -q '"Manager"'` would pass on the very
  # first poll regardless of whether a real verdict exists. A non-null agents.manager.last_updated
  # alone isn't enough either: manager_node() (services/scheduler/src/graph/manager.py) writes a
  # ProcessHistory row with status="failed" (and no write_agent_output call) if score_verdict
  # throws, and symbol_detail() folds every history entry into last_updated_by_agent regardless
  # of status -- so a failed Manager run would also produce a non-null last_updated with no
  # verdict ever written. compute_verdict() (services/mcp-server/src/tools/scoring.py) always
  # returns a non-empty "label" string on both its return paths, and label is only ever written
  # via write_agent_output on the success path in manager.py, so requiring both label and
  # last_updated to be truthy is what actually distinguishes "a real verdict was written" from
  # "the pipeline touched this symbol (successfully or not)".
  if echo "$DETAIL" | python3 -c "
import json, sys
data = json.load(sys.stdin)
manager = data.get('agents', {}).get('manager', {})
sys.exit(0 if manager.get('label') and manager.get('last_updated') else 1)
"; then
    echo "Manager verdict present. Smoke test passed."
    exit 0
  fi
  sleep 2
done

echo "FAILED: no Manager verdict for AAPL after 90s"
exit 1
