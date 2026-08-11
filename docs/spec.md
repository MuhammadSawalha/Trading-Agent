# Stock Research Agent — Design Specification

## 1. Problem Statement

Producing a balanced, evidence-based view of a stock today means manually
cross-referencing 6+ data sources — fundamentals, technicals, options
activity, insider/institutional filings, news sentiment, and macro
backdrop — then holding the whole picture in your head to weigh bull and
bear evidence against each other. That process takes roughly an hour per
stock and leaves no durable record of *why* a conclusion was reached.

This system cuts that to about two minutes by running a multi-agent
pipeline that fetches the same categories of data, has specialist agents
interpret each category, has dedicated agents argue the bull and bear case
against each other, and produces a final composite research score —
**with every claim in that score traceable back to the specific data that
produced it.**

**Explicitly out of scope / non-goals:**

- This is a **research and analysis tool, not a trading-execution system**.
  No component of this system places, modifies, or is capable of placing a
  real order. No execution tool exists in any agent's tool set.
- The composite score is **not a validated trading signal**. No
  backtesting against historical forward returns has been performed on the
  scoring formula (§4.5.1) or on the system's directional calls. The score
  must not be presented, in the UI or elsewhere, as investment advice.
  Validating the formula's weights against historical outcomes is named
  explicitly as future work, not part of this project.
- Single-user tool. No accounts, no auth, no per-user data isolation.

## 2. High-Level Architecture

### 2.1 Model constraint (hard, non-negotiable)

Every LLM call in the system uses exactly one model, via AWS Bedrock:

```python
model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
model_provider = "bedrock_converse"
region_name = "us-east-1"
```

This is a deliberate design constraint, not a limitation to be worked
around. The architecture divides work so the model only ever does what it
is uniquely suited for — language understanding, argumentation, and
judgment calls — while numeric aggregation, scheduling, caching, and rate
limiting are deterministic Python that never calls the model:

| Task | Owner |
|---|---|
| Interpreting a data category into a structured claim | LLM (specialist agents) |
| Constructing/rebutting an argument | LLM (Bull/Bear agents) |
| Judging whether a rebuttal actually succeeded | LLM (Bear agent) |
| Synthesizing risk factors into a level | LLM (Risk agent) |
| Answering free-form user questions | LLM (Chat) |
| Combining claims into a score | Deterministic Python (Manager) |
| Fetch scheduling, caching, rate limiting, circuit breaking | Deterministic Python |

A single small model is sufficient because every LLM-facing task is
narrow, well-scoped classification or argumentation over data that's
already been fetched and structured — not open-ended reasoning over raw
numbers.

### 2.2 Service topology

Four independently deployable workloads, matching the course's
one-workload-per-service Kubernetes/Terraform expectations:

```
                              ┌─────────────────────────┐
                              │        Frontend          │
                              │  (React, static, Nginx)  │
                              └────────────┬─────────────┘
                                           │ HTTP + SSE
                                           ▼
                              ┌─────────────────────────┐
                              │       API Backend         │
                              │  (FastAPI, HPA 2-4 reps)  │
                              │  HTTP API, SSE, Chat LLM  │
                              └──────┬─────────┬──────────┘
                                     │         │
                        reads/writes │         │ MCP (process-history
                                     ▼         │  tool only)
                          ┌────────────────┐   │
                          │   DynamoDB      │   │
                          │  (3 tables)     │◄──┼───────────┐
                          └────────▲────────┘   │           │
                                   │            ▼           │
                        writes     │   ┌─────────────────┐  │
                                   │   │   MCP Server     │  │
                    ┌──────────────┴───┤  (self-built,    │◄─┘
                    │                  │   FastMCP)        │
                    │                  └───┬─────────┬─────┘
                    │                      │         │
         ┌──────────┴──────────┐           │         │
         │      Scheduler        │◄─────────┘         │
         │  (LangGraph pipeline, │  MCP (35 tools:     │
         │   1 replica, no HPA)  │  Finnhub/FMP/FRED/   │
         └───┬────────┬──────────┘  Marketaux + 2       │
             │        │             custom tools)        │
    MCP      │        │ MCP                               │
             ▼        ▼                                   │
  ┌─────────────┐  ┌──────────────────┐                    │
  │ TradingView  │  │  Stock Scanner    │                    │
  │ MCP (3rd-    │  │  MCP (3rd-party,  │                    │
  │ party, 18    │  │  13 tools: scan,  │                    │
  │ tools)       │  │  EDGAR filings)   │                    │
  └─────────────┘  └──────────────────┘
```

**Frontend** — static React build served by Nginx. No server-side logic.

**API Backend** — stateless, horizontally scaled (HPA, CPU-based, 2–4
replicas). Serves the HTTP API and web UI's data needs, SSE streams for
live updates, and the Chat agent. Reads `AgentOutputs`/`ProcessHistory`
from DynamoDB directly; is an MCP client of the self-built server only,
for the process-history-query tool. Makes no live third-party tool calls
and never re-runs the analysis pipeline.

**Scheduler** — single replica, deliberately **not** HPA-scaled: it is
cadence-driven, not request-driven, and concurrent replicas would double
every scheduled fetch and corrupt rate-limit/circuit-breaker state. Owns
the entire LangGraph pipeline end to end (Input Data Agent → four
specialists → Bull/Bear/Risk → Manager) and all provider scheduling, rate
limiting, and the circuit breaker. Is the MCP client for all three MCP
servers, including calling the self-built server's manager-scoring-formula
tool so that step is fully traceable rather than an opaque in-process
function call.

**MCP server (self-built)** — its own Deployment, built with the official
MCP Python SDK (`FastMCP`). Wraps Finnhub (11), FMP (10), FRED (11),
Marketaux (1) — 33 provider tools — plus 2 custom, provider-independent
tools: the deterministic manager-scoring formula, and a process-history
query tool. 35 tools total.

Two third-party, self-hosted MCP servers (TradingView MCP, 18 tools; Stock
Scanner MCP, 13 tools) are connected to as external dependencies, not
deployed by this project.

### 2.3 Why no SQS/SNS, and where S3 is used

The course covers SQS/SNS and S3, but they're adopted only where there's a
genuine need, per the project's own scope discipline:

- **No SQS/SNS.** The per-provider schedules (§7) are irregular and
  market-hours-aware — 30-minute daytime cadences, 90-minute
  after-hours cadences, hard pauses overnight — which fit an in-process
  async scheduler inside the single-replica Scheduler service far better
  than either coarse cron expressions or a queue. There is no genuine
  async fan-out or multi-consumer need at single-user scale that a queue
  would solve.
- **S3, narrowly.** DynamoDB items are capped at 400KB. Some tool
  responses — full SEC filing text, large financial-statement dumps — can
  exceed that. When a tool result's serialized size passes a threshold
  (300KB), the Input Data Agent writes the payload to S3 and stores an S3
  key + small metadata in `ToolResults` instead of the payload itself.
  Everything under the threshold stays inline in DynamoDB. This is the
  only S3 use in the system.

## 3. Data Sources — Tool Inventory (65 tools, 6 providers)

**Finnhub (11, wrapped by self-built MCP server):** Company Profile,
Peers, Basic Financials, Earnings Calendar, Earnings Surprises, Insider
Transactions, Insider Sentiment, Lobbying Data, USA Spending, Company
News, Quote.

**FMP (10, wrapped by self-built MCP server):** Income Statement, Balance
Sheet Statement, Cash Flow Statement, Financial Ratios, Key Metrics, DCF
Valuation, Ratings Snapshot, Dividends Calendar, Stock Splits Calendar,
Economic Indicators.

**FRED (11, wrapped by self-built MCP server):** Federal Funds Rate,
10-Year Treasury Yield, 2-Year Treasury Yield, CPI, Unemployment Rate,
Nonfarm Payrolls, Real GDP, VIX, Consumer Sentiment, Series Search,
Release Calendar.

**Marketaux (1, wrapped by self-built MCP server):** News: All
(per-article sentiment, entity-tagged).

**Custom, provider-independent (2, self-built MCP server):** manager
scoring formula (§4.5.1), process-history query.

**TradingView MCP (18, third-party, self-hosted):** Stock Screener, Top
Gainers Screener, Top Losers Screener, Bollinger Squeeze Scanner, Smart
Volume Scanner, Full Technical Analysis, Multi-Timeframe Analysis, Volume
Confirmation Analysis, Candlestick Pattern Analysis, Multi-Agent Market
Debate, Combined TA+Sentiment+News, Extended-Hours Stock Price, Options
Chain, Unusual Options Activity, Strategy Backtest, Strategy Comparison
Race, Walk-Forward Backtest, Market Sentiment (Reddit).

**Stock Scanner MCP (13, third-party, self-hosted):**
`tradingview_scan`, `tradingview_compare_stocks`, `tradingview_top_volume`,
`tradingview_sector_performance`, `edgar_search`, `edgar_company_filings`,
`edgar_institutional_holdings`, `edgar_ownership_filings`,
`tradingview_technicals`, `tradingview_market_indices`,
`tradingview_volume_breakout`, `edgar_company_facts`, `edgar_insider_trades`.

**Dual-source (1, spans two providers):** Analyst Price Targets — queries
TradingView and FMP independently and cross-checks them, since a single
source can carry an outlier estimate the other corroborating source
doesn't.

**Symbol validation:** no dedicated symbol-search tool exists in this
inventory. Adding a ticker in the UI validates by calling Company Profile
synchronously; an empty/error response rejects the add with an inline
error.

## 4. Components

### 4.1 Input Data Agent (deterministic, no LLM call)

Runs inside the Scheduler. Owns every tool call:

- Checks DynamoDB (`ToolResults`) first; only calls a live tool when that
  tool's own schedule (§7) says it's due.
- **New symbol added to the watchlist:** performs a full, immediate fresh
  fetch of every relevant tool for that symbol, bypassing the normal
  rotation, and runs the pipeline once for it right away.
- **News-diff gate:** fetches the latest Marketaux articles for a symbol,
  diffs the returned article UUIDs against what was stored on the
  previous fetch, and routes to the Sentiment specialist (via a LangGraph
  conditional edge) only when there are genuinely new UUIDs. If nothing
  changed, the rest of the pipeline is skipped entirely for that run and
  the previously cached agent outputs are served as-is. This is the
  mechanism that keeps the (costly) full reasoning pipeline from re-running
  on every scheduling tick.
- Applies per-provider rate limiting/scheduling (§7) and the TradingView
  circuit breaker.
- Writes every tool result to `ToolResults` (or S3 + pointer, §2.3), and
  appends a status entry to `ProcessHistory` for every agent run —
  including `started`/`finished` transitions per agent, which is what
  powers both the "last updated" UI (§8) and the live pipeline visualizer
  (§8.3).

### 4.2 Specialist agents (LLM: Fundamentals, Technical, Sentiment,
Macro/Options)

Run in parallel, after the Input Data Agent, one per data category. Each
reads its slice of fetched data and interprets it into one or more
structured claims:

```json
{
  "strength": "strong" | "moderate" | "weak",
  "corroborated": bool,
  "rationale": "<short natural-language justification>"
}
```

A narrow classification/interpretation task per agent, well suited to
Haiku with a tightly scoped system prompt and structured tool-call output.

### 4.3 Debate agents (LLM: Bull, Bear)

Run in parallel, after all four specialists finish.

- **Bull** constructs the strongest bullish case from the specialists'
  claims.
- **Bear** does the same for the bearish case, then gets a **rebuttal
  round**: shown the opposing side's specific claims, it must either
  directly rebut a named claim with evidence or concede it.
- A model judgment call then decides whether a given rebuttal actually
  succeeded, setting `rebutted_undefended: true` on the affected claim
  when it did. This is a real reasoning step feeding the Manager's scoring
  (§4.5.1), not a formality — and the clearest example in the system of
  something a formula structurally cannot do.

### 4.4 Risk agent (LLM)

Runs after the debate agents, synthesizing two categories into one
`risk_level` (`low`/`medium`/`high`):

- **Market risk** — volatility, macro backdrop, liquidity, options-implied
  risk, upcoming scheduled events (earnings, macro releases), ownership
  instability signals.
- **Data-reliability risk** — cross-source disagreement on a metric, or a
  claim resting on data flagged unreliable elsewhere in the pipeline.

The Risk agent **never argues a direction**. This is enforced structurally
in its output schema (`does_not_take_a_directional_stance: true`), not
just by prompt convention — the field is validated on every Risk agent
response before it's accepted.

### 4.5 Manager agent (deterministic, no LLM call)

Runs after Bull, Bear, and Risk all finish. Combines their outputs into a
final verdict via a documented formula (§4.5.1), calling the self-built
MCP server's scoring tool rather than a bare in-process function, so the
arithmetic step is traceable through the same tool-call log as every LLM
step.

#### 4.5.1 Scoring formula

1. **Per-claim score** = base value for strength (strong/moderate/weak),
   adjusted by:
   - a corroboration bonus (independently confirmed by 2+ sources)
   - a penalty if the claim rests on data flagged unreliable elsewhere in
     the pipeline
   - a penalty if the claim was rebutted and not defended
   - for news-sourced claims: an adjustment for how fresh/central the
     article is
   - for unusual-volume-sourced claims: a log-compressed, liquidity-gated
     adjustment for how extreme the reading is
2. **Net directional score** (−100 to +100) = normalized dominance of
   total bull claim weight vs. total bear claim weight.
3. **Confidence** (0–100%), computed separately from direction: scales
   with how lopsided the net score is, penalized by flagged/rebutted
   claims, boosted by corroboration.
4. **Risk adjustment**: the risk level scales confidence down — never
   flips direction. Low risk leaves confidence unchanged; high risk cuts
   it substantially.
5. Final labeled verdict, e.g. `"Bullish, moderate confidence"`.

**Every constant in this formula is a documented design decision, not an
empirically validated weight.** Validating it against historical forward
returns is explicitly out of scope for this project (§1) and is named as
future work.

### 4.6 Chat (LLM)

Runs in the API Backend. Answers free-form user questions about the
user's whole watchlist (not scoped to one stock), grounded by:

- Reading `AgentOutputs` directly from DynamoDB for the relevant symbol(s)
  — structured context-stuffing, not an embeddings/vector-search
  pipeline. No vector DB is introduced in this project.
- Calling the self-built MCP server's process-history-query tool when the
  question concerns timing or audit trail ("when was this last updated",
  "why did the score change").

Never triggers a fresh pipeline run — every answer is grounded in what's
already cached.

### 4.7 Scheduler service

Hosts the Input Data Agent and the full LangGraph graph (§4.1–4.5). A
single async scheduler loop drives each provider's cadence (§7),
market-hours-aware, and triggers immediate out-of-band runs for
watchlist-add events. Single replica by design (§2.2).

### 4.8 API Backend

FastAPI service. Serves: the dashboard/watchlist/detail-modal data reads,
SSE streams (§8.3), the Chat endpoint, and watchlist add/remove
operations (validated per §3, written directly to the watchlist config in
DynamoDB, which the Scheduler picks up on its next loop tick or
immediately for adds).

### 4.9 MCP server (self-built)

FastMCP-based, matching the pattern of the two third-party servers this
project already integrates with. 35 tools (§3). Deployed independently
(§2.2), called only by the Scheduler (all tools) and the API Backend
(process-history-query tool only).

## 5. Data Flow

**1. Scheduled pipeline run**
Scheduler tick → Input Data Agent checks `ToolResults` cache per §7 →
live tool calls only where due → news-diff gate decides whether to
proceed → if proceeding: four specialists (parallel) → Bull, then Bear
(sequential — Bear's rebuttal round needs Bull's completed claims), then
Risk → Manager (calls scoring tool) → results written to `AgentOutputs`,
transitions appended to `ProcessHistory` throughout.

**2. New symbol added**
User adds ticker in UI → API Backend validates via Company Profile call →
written to watchlist config → Scheduler detects the addition and runs a
full fresh fetch + full pipeline immediately for that symbol, out of
rotation.

**3. News-triggered partial cascade**
Scheduler tick → Marketaux fetch for a symbol → new article UUIDs found →
Sentiment specialist re-runs → downstream agents (Bull/Bear/Risk/Manager)
re-run using the fresh Sentiment output alongside the other specialists'
still-cached outputs → `AgentOutputs` updated only for the agents that
actually changed, each with its own new `ProcessHistory` timestamp — this
is what the color-differentiated "last updated" UI (§8) makes visible.

**4. Discovery dashboards**
Scheduler's discovery-tier loop (§7) → TradingView/Stock-Scanner screener
tools → results written to a small discovery cache in DynamoDB (part of
`ToolResults`, keyed by dashboard name rather than symbol) → API Backend
serves it read-only to the frontend.

**5. Chat**
User question via API Backend → relevant symbol(s) inferred from the
question and the user's watchlist → `AgentOutputs` read directly +
process-history tool called as needed (§4.6) → Haiku call over the
assembled context → natural-language answer.

**6. Live pipeline visualizer**
User opens the visualizer → API Backend SSE endpoint server-side polls
`ProcessHistory` for the in-flight run's per-agent status transitions
every ~1–2s → emits only diffs → frontend renders each agent node's
idle → running → finished transitions in real time, in the actual
dependency order from §4.

## 6. Persistence — DynamoDB

Three tables, provisioned per environment (`dev`/`prod`) via Terraform:

- **`ToolResults`** — `PK = SYMBOL#TOOL` (or `PK = DASHBOARD#NAME` for
  discovery-tier results). Latest raw tool result, or an S3 pointer +
  metadata for oversized payloads (§2.3). A native DynamoDB TTL attribute
  is set to match that tool's own refresh schedule (§7) — expiry is
  automatic, never manually managed.
- **`AgentOutputs`** — `PK = SYMBOL`, `SK = AGENT_NAME`. Latest computed
  output per agent per symbol, enabling fast dashboard/modal/chat reads
  with no pipeline re-run required.
- **`ProcessHistory`** — `PK = SYMBOL`, `SK = TIMESTAMP#AGENT`.
  Append-only log of every agent run: why it ran (scheduled refresh vs.
  news-triggered cascade vs. new-symbol-added first run) and its
  started/finished status transitions. Powers the "last updated" UI, the
  live pipeline visualizer, and the process-history-query MCP tool.

## 7. Scheduling and Rate Limiting (per provider)

Each provider has a different real-world constraint, so each gets its own
strategy:

| Provider | Constraint | Strategy |
|---|---|---|
| Marketaux | Hard daily cap | Watchlist split into 4 batches; polled every 30 min in regular market hours, every 90 min pre-market/after-hours, not polled overnight. Comfortably under quota with a protective safety cap as backstop. |
| FMP | Hard daily cap | 30-symbol watchlist on a 3-day rotation (10 refreshed/day), since fundamentals only change on quarterly filings. Per-symbol tools (statements, ratios, DCF, ratings, price targets) rotate; global tools (dividend/split calendars) are fetched once regardless of watchlist size. |
| Finnhub | Per-minute cap, not daily | Static company data once/day; quotes and news polled frequently during market hours, protected by a sliding-window rate limiter rather than a daily budget. |
| FRED | Per-minute cap, effectively unlimited at this scale | Slow macro series once/day; VIX hourly during market hours, since it's the one series that genuinely moves intraday and feeds the Risk agent. |
| TradingView-backed tools (both third-party servers) | No stated quota, but a shared, real dependency on TradingView's scanner infrastructure | Circuit breaker (not a quota scheduler): after a small number of consecutive failures, stop calling for a cooldown period and serve the last known-good cached value, clearly marked stale. Both servers share one breaker since they depend on the same upstream service. |
| Discovery dashboards (Top Gainers/Losers/Volume, Volume Breakout — TradingView/Stock-Scanner screener tools) | Same shared TradingView dependency as above; market-wide context, not per-symbol analysis, so it doesn't need near-real-time refresh | Every 30 minutes, matching the same regular-market-hours cadence already established for Marketaux — reusing that number rather than introducing a new one. Active 4:00am–8:00pm ET (covering pre-market through after-hours); **paused overnight, 8:00pm–4:00am ET**, explicitly, not just inherited from the Marketaux precedent. Governed by the same shared circuit breaker as the rest of the TradingView-backed tools. |

Watchlist size: **30 symbols maximum**, user-managed (add via search,
remove individually), separate from the four unmanaged discovery panels.

## 8. Frontend

Two-column layout, exactly 50/50 width split.

### 8.1 Left half

- 2×2 grid of four discovery dashboards (Top Gainers, Top Losers, Top
  Volume, Volume Breakout — 10 stocks each). Read-only, not clickable,
  refreshed per the discovery-tier schedule (§7).
- Ticker search/add box below the grid.
- **Selected Companies** panel (max 30, user's managed watchlist) — each
  row: symbol, price, % change, current verdict, "last updated," remove
  (×) button. Rows are clickable.
  - Clicking a row opens an in-page modal (dimmed backdrop, smaller than
    the viewport, closeable without navigation) showing:
    - The full pipeline (Input Agent → 4 specialists → Bull/Bear/Risk →
      Manager), each node showing its own "last updated" timestamp,
      color-differentiated so a recently-updated agent (e.g. Sentiment,
      2 minutes ago from breaking news) is visually distinct from one
      that hasn't changed in longer (e.g. Fundamentals, an hour old) —
      making a partial, news-triggered cascade visible at a glance.
    - A results chart (bull/bear/risk scores), key supporting
      claims/proofs per side, and the Manager's final verdict with
      confidence %.
  - Reads entirely from the DynamoDB cache; opening it never triggers a
    live pipeline re-run.

### 8.2 Right half

- Chat panel, scoped to the whole watchlist, so cross-symbol questions
  work naturally.
- Live news feed panel below it, tagged per company, updating as new
  articles are detected by the Input Data Agent.

### 8.3 Live pipeline visualizer (standalone, demo/observability)

An animated view of a single analysis run in progress: each agent node
transitions idle → running → finished in real time (respecting the
dependency order from §4), colored per state, clickable to inspect what
that agent produced. Distinct from the cached per-company modal — this
makes a live run visible end-to-end, useful for both debugging and
demonstrating the reasoning is real. Driven by SSE (§5.6).

## 9. Infrastructure

- **Kubernetes on self-managed EC2 instances — no EKS.**
- Separate `dev` and `prod` namespaces, distinct configuration per
  namespace, DynamoDB tables suffixed/scoped per environment.
- Every workload (frontend, API backend, scheduler, MCP server) gets
  liveness/readiness probes, resource requests/limits, ConfigMaps, and
  namespace-scoped Secrets. HPA applies only to the frontend and API
  backend (request-driven); the Scheduler is intentionally a fixed single
  replica (§2.2), and the MCP server may get a modest HPA range since it's
  stateless request/response.
- **Scheduler liveness probe (non-generic, by requirement):** because the
  Scheduler is a single, non-redundant replica (§2.2, §10), a generic
  process-alive probe is not sufficient for it — it would restart the pod
  on a crash but would never catch a hang. The Scheduler exposes a
  heartbeat (a last-tick timestamp, updated at the end of every scheduling
  loop iteration); its liveness probe checks that timestamp against the
  expected cadence and fails the probe — forcing a restart — if the
  Scheduler has gone stale beyond a defined threshold, not just if the
  process has died. The other three workloads use a standard
  process/HTTP-health liveness probe, since their redundancy makes a
  hung-but-alive instance a much lower-stakes failure.
- **Secrets**: provider API keys (Finnhub, FMP, FRED, Marketaux) as
  Kubernetes Secrets, separate per namespace, populated from GitHub
  Actions secrets at deploy time. AWS access (Bedrock, DynamoDB, S3) comes
  from an IAM role attached as an **EC2 instance profile** on the worker
  nodes — there's no IRSA/OIDC without EKS — scoped per environment.
- **All AWS resources provisioned via Terraform**: VPC/subnets, the EC2
  instances backing the cluster, the DynamoDB tables, the S3 bucket for
  oversized tool payloads, and the IAM roles/policies above. No manual
  console setup.
- **Packaging**: Helm charts for all four workloads.
- **CI/CD (GitHub Actions)**: run tests on every PR; on merge to `main`,
  build/push images and auto-deploy `dev`. `prod` deployment is
  **ArgoCD-managed** (GitOps, pull-based) — CI updates a prod image
  tag/values path, ArgoCD syncs it, gated by manual approval. Test results
  reported clearly via the GitHub Actions job summary.
- **Networking**: Nginx Ingress + ELB exposes the frontend and API
  backend per the course's networking material.
- **Observability**:
  - kube-prometheus-stack (Prometheus + Grafana + Alertmanager) + Loki,
    in-cluster, for infra/service metrics and logs across all four
    workloads — request latency, error rates, tool-call failures,
    circuit-breaker trips, scheduler cadence adherence.
  - **Langfuse Cloud** (SaaS free tier) for LLM/agent-level tracing —
    model calls, tool calls, latencies per agent node — avoiding an
    in-cluster Postgres/ClickHouse/Redis stack just for tracing.
  - `ProcessHistory` (§6) is treated as a first-class observability data
    source in its own right, not just an application feature.
  - Alerts on: error rate spikes, tool timeouts, circuit-breaker trips,
    scheduler falling behind its own cadence.
  - A dashboard combining Grafana (system health) and Langfuse (trace-level
    agent debugging) for an at-a-glance view of both layers.

## 10. Error Handling

- **Scheduler single point of failure (by design):** the Scheduler is the
  system's single point of failure by design (§2.2) — it deliberately runs
  as one non-redundant replica, unlike the Frontend, API Backend, and MCP
  server, which all have HPA-backed redundancy to fall back on if one
  instance misbehaves. If the Scheduler hangs rather than crashes (a
  deadlock, or a call that never returns), the entire pipeline silently
  stops with nothing to pick up the slack. This is why its liveness probe
  is specified separately in §9 as a heartbeat/last-tick check rather than
  a generic process-alive check: a generic probe would miss a deadlocked
  Scheduler entirely, since the process is still "alive" from Kubernetes'
  perspective while doing nothing.
- **Circuit breaker** (TradingView-backed tools, shared across both
  third-party servers and the discovery tier): after a small number of
  consecutive failures, stop calling for a cooldown period and serve the
  last known-good cached value, clearly marked stale, rather than failing
  the request.
- **Per-provider retry/backoff**, tuned to each provider's actual
  constraint (§7) — sliding-window for per-minute caps, hard stop for
  daily caps.
- **News-diff gate failure**: if the diff check itself fails (e.g.
  Marketaux unreachable), the Input Data Agent skips the cascade for that
  tick and retries on the next scheduled tick — it never blocks or
  crashes the rest of that symbol's scheduled run.
- **Oversized tool payloads**: transparently offloaded to S3 (§2.3)
  instead of failing on DynamoDB's item-size limit.
- **Guardrail flags propagate, not fail**: a claim resting on
  data flagged unreliable elsewhere in the pipeline is penalized in the
  Manager's scoring (§4.5.1), not dropped — the system always produces a
  verdict, with the uncertainty reflected in confidence rather than a
  hard failure.
- **Risk agent schema enforcement**: `does_not_take_a_directional_stance`
  is validated on every response; a response that fails this check is
  rejected and retried rather than silently accepted.
- **LLM/tool-call failures**: bounded retries per agent node, then
  graceful termination for that run — the last good cached output for
  that symbol/agent stays visible in the UI (clearly marked stale) rather
  than the pipeline hanging or the user seeing a partial/broken result.
- **SSE disconnects**: client reconnects automatically; since the API
  Backend polls DynamoDB rather than holding in-memory stream state, a
  reconnect from any replica picks up current state with no data loss.
- **Kubernetes probes**: liveness/readiness probes on all four workloads
  in both namespaces, so a wedged pod is restarted rather than silently
  serving broken requests.
- **No execution path exists** (§1) — the strongest possible form of
  error handling for the one failure mode that must never occur.

## 11. Testing Strategy

| Layer | What's tested | How | Success criteria |
|---|---|---|---|
| Manager scoring formula | Every branch of the formula (§4.5.1): strength bases, corroboration bonus, unreliable-data penalty, rebutted-undefended penalty, news freshness/centrality adjustment, volume-extremity adjustment, risk-adjustment scaling | Pure unit tests, **zero mocking** — the formula has zero external dependencies, a direct benefit of keeping arithmetic out of the LLM layer | Deterministic, exact output for fixed input, run on every PR |
| Scheduler / rate limiters / circuit breaker | Cadence correctness per provider (§7, including the discovery-tier 30-min/pause-window logic), cache-hit/miss behavior, sliding-window and daily-cap behavior, circuit-breaker trip/cooldown/reset | Isolated unit tests with time mocked/frozen | Correct behavior at every cadence boundary and failure-threshold edge, run on every PR |
| Specialist / debate / risk agent logic | Claim structure validity, Risk agent's directional-neutrality schema enforcement, Bear's rebuttal-success judgment wiring | Unit tests with the LLM (Bedrock) and all external tool calls mocked | Deterministic given a mocked LLM response, no network calls, run on every PR |
| News-diff gate | New-UUID detection triggers the cascade; unchanged UUIDs skip it | Unit tests with mocked Marketaux responses | Correct routing decision in both cases |
| Self-built MCP server (integration) | Tool discovery and end-to-end tool-call round trips for all 35 tools | Real MCP transport (not mocked at the transport layer), per course requirement | All 35 tools discoverable and callable through the real protocol in CI |
| End-to-end smoke test | Basic deploy health | After `dev` auto-deploy in CI, hit health and a representative data endpoint | Deploy succeeds, endpoints respond correctly |

## 12. Future Work

- Backtesting the Manager scoring formula's constants against historical
  forward returns (explicitly out of scope for this project, §1).
- Multi-user accounts/auth.
- Additional asset classes beyond what the current 6 providers cover.
