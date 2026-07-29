# Trading Agent — Design Specification

## 1. Problem Statement

Retail traders want to test trading strategy ideas, track news and
institutional/insider activity relevant to their watchlist, and get advisory
buy/sell/stop suggestions — without writing code, juggling many data sources, or
handing an AI agent the ability to execute real trades.

Today this means manually cross-referencing a news feed, a fundamentals site, a
charting tool, SEC filings, and a separate backtesting script, then keeping the
results of each experiment in a spreadsheet (or nowhere at all). The Trading Agent
replaces that with a single agent interaction backed by real market, fundamentals,
and filings data, and turns backtesting from a one-off scripting exercise into a
saved, queryable, reusable strategy library.

**Measurable value:** collapses hours of manual cross-referencing into one agent
query, and makes every backtest a durable, comparable artifact instead of a
throwaway script run.

## 2. Safety Boundary (non-negotiable)

**The agent is advisory only.** It generates suggestions and notifications; it
never places, modifies, or cancels a real order.

This is enforced architecturally, not just by prompt instruction: no
order-execution tool is ever registered on any agent's tool set, in any
environment. There is nothing an agent could call to touch a real brokerage
account even if it wanted to. Every signal the system produces — buy/sell,
move-stop-loss, set-limit, set-stop — is a structured suggestion surfaced as a
notification, never an executed action.

## 3. Scope

- **Primary:** US equities and ETFs.
- **Secondary, deferred out of v1:** crypto. Documented as a future extension (see
  §15) — it needs a different price source, different backtest data handling, and
  a UI asset-type switch, which is meaningful scope for the same deadline.
- **Not in scope:** forex, options/derivatives.

## 4. Architecture

### 4.1 High-level shape

```
Terraform (per env: dev, prod)
  VPC/subnets, 3x EC2 (k8s), S3, DynamoDB, SQS, SSM Parameter Store, ECR, IAM
        │
        ▼
Kubernetes cluster (1 control-plane + 2 workers)
  ├── dev namespace   (own ConfigMaps/Secrets, own AWS resources)
  └── prod namespace  (own ConfigMaps/Secrets, own AWS resources)
        │
        ▼
ingress-nginx
        │
        ▼
React frontend  ──►  FastAPI backend (HTTP API)
                          │
                          ▼
                LangGraph multi-agent pipeline
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
     TradingView MCP server   Domain-Data MCP server (self-built)
     (technicals, sentiment,   (Finnhub, FMP, FRED, edgartools,
      confluence check)         MT5-derived historical data from S3)
              │                       │
              ▼                       ▼
         external market data & filings sources
```

Everything above the ingress line runs in Kubernetes; everything AWS-managed is
provisioned exclusively through Terraform — no manual console changes, ever, in
either environment.

### 4.2 Multi-agent design

The signal pipeline is decomposed into distinct LangGraph nodes, each with its own
system prompt defining that node's persona, capabilities, and boundaries, rather
than one combined prompt doing everything:

- **News analyzer** — sentiment and impact assessment of a single news item.
- **Company analyzer** — fundamentals sanity-check against the news analyzer's
  read (does the reaction make sense given the company's actual financials?).
- **Signal scorer** — combines both upstream assessments into a confidence score
  and decides whether the bar for a notification is crossed.

A **devil's-advocate validation agent** — a stretch goal — would sit after the
signal scorer and argue against a signal before it's sent, as an explicit
adversarial check rather than a second vote in the same direction.

The **chat entry point** uses the same pattern: an advisory-only persona, an
explicit list of tool capabilities, and an explicit boundary (no trade execution,
ever) baked into its system prompt.

### 4.3 MCP integration pattern

`langchain-mcp-adapters`'s `MultiServerMCPClient` connects to two MCP servers over
stdio transport:

1. **TradingView MCP** (third-party, `github.com/atilaahmettaner/tradingview-mcp`)
   — technicals (RSI, MACD, SMA/EMA, Bollinger, ATR, ADX, stochastic,
   support/resistance), a computed trade setup (entry/stop/targets/risk-reward),
   and, via its `combined_analysis` tool, bundled news sentiment and a confluence
   check when a Marketaux key is configured.
2. **Domain-Data MCP server** (self-built) — exposes Finnhub, FMP, FRED,
   edgartools (insider transactions, 13F filings), and S3-read access to
   MT5-derived historical OHLCV as MCP tools, rather than as plain LangChain
   functions bound directly in-process.

Both servers' tools are auto-discovered by `MultiServerMCPClient` and bound to a
single LangGraph `create_react_agent`. The LLM decides which tool to call and with
what arguments — this is not manually scripted branching logic. Building the
second server (rather than wrapping those integrations as in-process LangChain
tools) is a deliberate choice: it satisfies the encouraged "build your own MCP
server" item, and gives the required MCP-transport integration tests (§12) a
first-party server to exercise over the real protocol, not just the third-party
one.

### 4.4 Two entry points, one agent

The scheduled signal pipeline (news → notification, live signal re-runs) and the
ad hoc agent chat panel (HTTP API + web UI) both drive the same LangGraph agent
and the same tool set. There is one system of record for what the agent can and
cannot do.

### 4.5 Well-crafted agent behavior

- Retries with backoff on transient tool/LLM failures.
- Graceful termination on unrecoverable errors — a clear terminal state surfaced
  to the caller, never a hang.
- Fallback behavior on degraded upstream data (§11).
- Clear, specific error responses returned to the user rather than silent
  failures or generic 500s.

## 5. Components

| Component | Type | Notes |
|---|---|---|
| News Poller | K8s CronJob | Polls Finnhub company news, pushes items to SQS |
| SQS queue (+ DLQ) | AWS, per env | Decouples polling from analysis |
| Agent Pipeline Consumer | K8s Deployment, HPA | Runs news analyzer → company analyzer → signal scorer per queued item |
| Backtest Engine | Service | Wraps the already-built `backtesting.py`-based engine |
| Strategy Library | DynamoDB, per env | Every backtest run saved with its parameters and metrics |
| Live Signal Job | K8s CronJob | Re-runs a saved strategy against live prices, emits structured suggestions |
| FastAPI backend | K8s Deployment, HPA | The required HTTP API; serves the frontend and the chat endpoint |
| React frontend | Static/served via backend | Dashboard, backtest view, strategy library table, chat panel |
| Agent Chat endpoint | FastAPI route | Same LangGraph agent/tools, ad hoc queries |
| TradingView MCP server | stdio subprocess | Third-party, technicals + sentiment/confluence |
| Domain-Data MCP server | stdio subprocess, self-built | Finnhub, FMP, FRED, edgartools, MT5-from-S3, plus a local technical-indicator fallback used when TradingView MCP is unreachable |

## 6. Data Flow

**1. News → notification**
Poll (CronJob) → SQS → news analyzer (sentiment/impact) → company analyzer
(fundamentals sanity-check) → signal scorer → in-app notification if confidence
crosses threshold.

**2. Backtest**
User sets strategy parameters and a starting balance in the UI → backtest engine
runs against S3-stored MT5 OHLCV → an equity curve (realized + unrealized P&L,
updated every bar) and a balance curve (realized only, updated on trade close) are
computed, with final balance as the headline metric → the run, its parameters, and
its metrics are saved to the DynamoDB strategy library.

**3. Live signal**
Live Signal CronJob re-runs a saved strategy against live prices (via the
Domain-Data MCP server) → produces a structured buy/sell/move-stop-loss/set-limit/
set-stop suggestion → delivered as an in-app notification. Advisory only, per the
safety boundary in §2.

**4. Chat**
User question via the HTTP API / web UI → the same LangGraph agent and tool set →
tool calls against both MCP servers (live data and/or saved strategy results) →
natural-language answer.

## 7. AWS Services & Terraform

All AWS resources below are provisioned exclusively via Terraform — no manual
console changes. Resources marked "per env" are fully duplicated across `dev` and
`prod` via Terraform workspaces, so activity in one environment can never touch
the other's data.

| Resource | Purpose | Scope |
|---|---|---|
| VPC + subnets | Network for the EC2 nodes | Shared |
| 3x EC2 | k8s control-plane + 2 workers | Shared cluster, hosts both namespaces |
| S3 (Terraform state) | Terraform state storage | Shared |
| DynamoDB (Terraform lock table) | Terraform state locking | Shared |
| S3 (MT5 data) | Historical OHLCV CSV/Parquet | Per env (prefix) |
| DynamoDB (strategy library) | Saved backtest runs, params, metrics | Per env |
| SQS (+ DLQ) | News pipeline queue | Per env |
| SSM Parameter Store | API keys: Finnhub, FMP, Marketaux, edgartools identity, Anthropic | Per env (path) |
| ECR | Container image registry | Shared repo, images tagged per env |
| IAM roles/policies | Least-privilege access for pods and CI | Per env where applicable |

## 8. Kubernetes Resource Layout

A single Kubernetes cluster hosts two namespaces, `dev` and `prod`, each with its own
ConfigMaps (non-secret configuration: thresholds, feature flags, API base URLs)
and Secrets (API keys pulled from the namespace-appropriate SSM path). Every
component in §5 is deployed independently into each namespace with its own
replica set, so a bad `dev` deploy never touches `prod`.

- **HPA** (CPU-based) on the FastAPI backend and the Agent Pipeline Consumer, per
  namespace.
- **ingress-nginx** with per-namespace Ingress resources (routed by host or path
  prefix) exposes each namespace's frontend/backend via the worker node's public
  IP.
- **Liveness/readiness probes** on all long-running Deployments (backend, pipeline
  consumer) in both namespaces — see §11.
- Resource requests/limits are deferred to implementation planning (`docs/plan.md`)
  and don't block this spec's approval.

## 9. CI/CD Pipeline

GitHub Actions, triggered on every pull request:

1. Lint.
2. Unit tests (mocked LLM and external services).
3. MCP-transport integration tests (real stdio transport against both MCP
   servers).
4. Results posted as a GitHub Actions job summary with a coverage badge on the
   PR.

On merge to `main`: build the Docker image(s), push to ECR, and deploy
automatically to the `dev` namespace. Deploying to `prod` is always a separate,
manually-gated step (e.g. a tag push or an explicit approval) — never automatic.

Terraform plan/apply runs as its own manually-gated workflow, reviewed before
apply, and is never triggered automatically on every push.

## 10. Observability

- **Metrics:** Prometheus scrapes the agent pipeline, backtest engine, and FastAPI
  backend — request latency, external API error/rate-limit counts, SQS queue
  depth, backtest job duration, signals generated/notified, and LLM call
  failures/timeouts — all labeled by namespace so `dev` and `prod` are
  distinguishable on the same dashboards.
- **Logs:** Loki aggregates pod logs across both namespaces.
- **Dashboard:** Grafana combines metrics and logs into an at-a-glance
  health-per-environment view.
- **Alerts:** Alertmanager rules cover SQS queue backing up, repeated external API
  failures, pod crash-looping, backtest job failures, and elevated LLM/tool error
  rate.

This is the "healthy" definition for the system: queues draining, external APIs
responding within their rate limits, no crash-looping pods, and LLM/tool call
error rates within a defined threshold.

## 11. Error Handling

- **Graceful degradation (validated pattern):** TradingView MCP's
  `combined_analysis` returns full technicals even when the optional Marketaux key
  is absent — the sentiment/news section degrades to a clear "Unavailable" flag
  instead of failing the whole call. This is the template followed elsewhere in
  the system: degrade a piece of the response, never fail the whole request over
  one missing optional input.
- **Technical-indicator fallback:** the Domain-Data MCP server computes indicators
  locally when the TradingView MCP server is unreachable, instead of failing the
  request outright.
- **Retry/backoff** tuned per data source to its actual free-tier limit (Finnhub
  60 calls/min, FMP, FRED, EDGAR).
- **SQS dead-letter queue** for news items that fail analysis repeatedly, so a
  poison message can't stall the pipeline.
- **LLM/tool-call failures:** bounded retries, then graceful termination — a
  visible "couldn't complete" response rather than a silent wrong answer or a
  hang.
- **Kubernetes probes:** liveness/readiness probes on the backend and pipeline
  consumer in both namespaces, so a wedged pod is restarted rather than silently
  serving broken requests.
- **Safety boundary, restated:** no order-execution tool exists in any agent's
  tool set, in any environment — the strongest possible form of error handling
  for the one failure mode that must never occur.

## 12. Testing Strategy

This is the project's test plan: what is tested, how, and the success criteria
for each layer.

- **Unit tests** — agent logic and both MCP servers' tools tested in isolation,
  with the LLM and external services (Finnhub, FMP, FRED, EDGAR, TradingView MCP)
  mocked. Includes the insider-transaction filter, which must accept only
  transaction codes "S" (sale) and "P" (purchase) and reject "M" (option
  exercise), "F" (tax withholding), and "G" (gift) as non-discretionary.
  *Success criteria:* deterministic, no network calls, run on every PR.
- **Integration tests** — the agent talks to the Domain-Data MCP server and the
  TradingView MCP server over the real MCP (stdio) transport, not mocked at the
  transport layer, verifying tool discovery and end-to-end tool-call round trips.
  *Success criteria:* both servers' tools are discoverable and callable through
  the real protocol in CI.
- **Backtest engine regression tests** — engine output for a fixed set of saved
  reference runs is compared against previously recorded, validated results
  (return, Sharpe ratio, max drawdown, trade count, win rate, profit factor) to
  catch unintended changes in engine behavior.
  *Success criteria:* computed metrics match the recorded reference within a
  small numerical tolerance.
- **End-to-end smoke test in CI** — deploy to the `dev` namespace, hit the backend
  health and chat endpoints, confirm a basic end-to-end response.
  *Success criteria:* deploy succeeds and both endpoints respond correctly.
- **Manual QA checklist** — dashboard, backtest view, strategy library, and chat
  panel walked through by hand before every `prod` deploy.
  *Success criteria:* all four flows work against real data with no console
  errors.

## 13. Data Sources

All of the following were empirically tested during research for this project;
all are free tier.

| Source | Provides | Notes |
|---|---|---|
| Finnhub | Live price/quote, company news, market cap, avg volume, 52-week high/low, beta | 60 calls/min free, no credit card |
| MetaTrader 5 export | Historical OHLCV for backtesting | One-time local export (not a live dependency), covers US stocks under "Stocks\USA"/"Stocks\USA2"; clean 3-year history at 1D/4H/1H, ~2yr at 15min, ~6mo at 5min, ~30d at 1min; stored as CSV/Parquet in S3 |
| FMP | Income statement, analyst estimates (annual only), macro indicators | Uses `/stable/` endpoints — the legacy `/v3/` paths were retired August 2025 |
| FRED | Fed funds rate, CPI, unemployment, GDP | Official Federal Reserve data, free with no key restrictions |
| edgartools (SEC EDGAR) | Insider trading (Form 4), SEC filings (10-K, 8-K) | Free, requires an identity string; insider transactions filtered to codes S/P only |
| edgartools (13F-HR) | Institutional 13F holdings | Quarterly, filed up to 45 days late — treated as long-term conviction context, not a timely signal |
| TradingView MCP | RSI, MACD, SMA/EMA, Bollinger, ATR, ADX, stochastic, support/resistance, computed trade setup, bundled news sentiment + confluence check | Sentiment/confluence require a free Marketaux key (100 req/day); technicals work fully without it |

### Explicitly rejected sources

| Source | Reason rejected |
|---|---|
| Yahoo Finance / yfinance | Returns 403 Forbidden from datacenter IPs (confirmed via direct testing) — too unreliable for a deployed agent |
| Alpha Vantage (intraday history beyond ~30 days) | Paywalled on the free tier despite docs suggesting otherwise (confirmed via direct testing) |
| Financial Datasets MCP | No free tier exists despite appearing to offer one; paid credits only |
| EODHD | Free tier is 20 calls/day, and fundamentals cost 10 calls/request — too thin for an unpredictable live agent workload |
| Telegram/social trading-signal groups | Deliberately excluded for data-quality and market-manipulation risk (pump-and-dump patterns), unlike SEC-sourced insider/institutional data |

## 14. Built vs. Not Yet Built

**Built and validated:** all data source integrations in §13, the backtest engine
(leverage, stop-loss, take-profit logic), the insider-trade transaction-code
filter, the MT5-to-CSV export pipeline.

**Designed but not implemented:** the self-built Domain-Data MCP server, the
DynamoDB strategy library, the live signal CronJob, chat agent wiring, the web UI,
and all Kubernetes/Terraform/CI-CD/observability infrastructure, including the
dev/prod split.

## 15. Future Extensions

- Crypto support (secondary asset class, deferred from v1 per §3).
- Multi-user accounts and authentication.
- Email (SES) or Slack-webhook notification channels, in addition to the in-app
  feed.
- The devil's-advocate validation agent (§4.2), if not completed as part of v1.
- Superpowers-style Agent Skills encoding domain workflows (e.g. a deploy skill,
  an alert-triage skill), per the course's extra-credit list.
