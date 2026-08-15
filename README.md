# Trading-Agent

## Quickstart

```bash
git clone <repo-url> && cd Trading-Agent
cp .env.example .env        # fill in provider keys
make up                     # docker compose up --build
python scripts/create_local_tables.py
```

## Tests

```bash
make install         # editable-install packages/common + all three services
make test-common     # packages/common
make test-mcp        # services/mcp-server
make test-scheduler  # services/scheduler
make test-api        # services/api-backend
```

## Observability

**Metrics endpoints.** All three backend services expose Prometheus metrics on
`GET /metrics`: mcp-server on port 8001, scheduler on 8002 (alongside `/health`), and
api-backend on 8080. Locally they are reachable at `http://localhost:{8001,8002,8080}/metrics`.
In the deployed frontend these are deliberately *not* proxied — `frontend/nginx.conf`
returns 403 for `/api/metrics`, since Prometheus scrapes the Services directly in-cluster.

**Install the stack** (once per cluster, into a `monitoring` namespace):

```bash
helm install kube-prometheus-stack kube-prometheus-stack \
  --repo https://prometheus-community.github.io/helm-charts \
  --namespace monitoring --create-namespace \
  -f monitoring/prometheus/values.yaml \
  --set grafana.adminPassword=<generated at install time, not committed>

helm install loki loki-stack \
  --repo https://grafana.github.io/helm-charts --namespace monitoring
```

**Wire up scraping and alerting:**

```bash
kubectl apply -f monitoring/prometheus/servicemonitors.yaml   # scrapes the `metrics` port of each Service in dev/prod
kubectl apply -f monitoring/prometheus/rules/alerts.yaml      # HighErrorRate, ToolCallTimeouts, CircuitBreakerOpen, SchedulerHeartbeatStale
```

The ServiceMonitor copies each Service's `app` label onto every sample (`targetLabels`),
which is what the alert annotations and the dashboard's per-service aggregations group by.

**Dashboard.** Import `monitoring/grafana/dashboards/system-health.json` via Grafana's
*Dashboards → New → Import → Upload JSON file*, then pick the Prometheus datasource when
prompted. It covers request latency (p50/p95) and 5xx rate per service, circuit-breaker
state, scheduler heartbeat age, and pod restarts.

**LLM tracing.** LLM calls in the scheduler and api-backend are traced to
[Langfuse Cloud](https://cloud.langfuse.com). Set `LANGFUSE_PUBLIC_KEY` and
`LANGFUSE_SECRET_KEY` (in `.env` for local docker-compose, or as Kubernetes secrets in a
cluster) or traces are silently dropped — the SDK only logs an auth warning, so nothing
else breaks locally if they are unset. Tracing lives in `packages/common/common/tracing.py`
and is pulled in via the `common[tracing]` extra; `services/mcp-server` intentionally omits
it, as it makes no LLM calls.
