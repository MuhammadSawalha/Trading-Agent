# Stock Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the multi-agent stock research system specified in `docs/spec.md` — a LangGraph pipeline on AWS Bedrock Claude Haiku, a self-built MCP server wrapping four data providers, two third-party MCP servers, a React frontend, and full Terraform/Kubernetes/CI-CD/observability infrastructure.

**Architecture:** Four independently deployable workloads (Frontend, API Backend, Scheduler, MCP Server) per spec §2.2. Deterministic logic (scoring formula, rate limiter, circuit breaker, Input Data Agent) is built and fully unit-tested before any LLM-dependent code, since it needs no mocking. The self-built MCP server and its 35 tools are built before the LangGraph graph that calls them. Infra (Terraform → Kubernetes/Helm → CI/CD → observability) is built last, layered onto working local (docker-compose) services.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, `langchain-mcp-adapters`, FastMCP (official MCP Python SDK), boto3 (Bedrock + DynamoDB + S3), React + TypeScript, Terraform, Kubernetes on self-managed EC2, Helm, ArgoCD, GitHub Actions, kube-prometheus-stack + Loki, Langfuse Cloud.

## Global Constraints

- Model config is fixed and must be used verbatim everywhere an LLM is called: `model = "us.anthropic.claude-haiku-4-5-20251001-v1:0"`, `model_provider = "bedrock_converse"`, `region_name = "us-east-1"` (spec §2.1).
- Watchlist max: 30 symbols (spec §7).
- DynamoDB item size limit is 400KB; any tool payload whose serialized size exceeds 300KB is offloaded to S3 with a pointer stored in `ToolResults` instead (spec §2.3).
- No SQS/SNS anywhere in this system (spec §2.3) — scheduling is in-process async, not queue-driven.
- The Scheduler runs as exactly one replica, never HPA-scaled (spec §2.2, §9, §10) — its liveness probe must be a heartbeat/last-tick check, not a generic process-alive check.
- Frontend, API Backend, and MCP Server may be HPA-scaled; Scheduler may not.
- AWS access from pods comes from an EC2 instance-profile IAM role (no IRSA/OIDC — no EKS). Provider API keys (Finnhub/FMP/FRED/Marketaux) come from Kubernetes Secrets, not SSM (spec §9).
- `dev` auto-deploys via GitHub Actions on merge to `main`; `prod` is ArgoCD-managed (GitOps), gated by manual approval (spec §9).
- Langfuse Cloud (SaaS), not self-hosted (spec §9).
- All AWS resources provisioned via Terraform — no manual console changes (spec §9).
- DynamoDB table key schemas are fixed (spec §6): `ToolResults` (`PK=SYMBOL#TOOL` or `DASHBOARD#NAME`), `AgentOutputs` (`PK=SYMBOL`, `SK=AGENT_NAME`), `ProcessHistory` (`PK=SYMBOL`, `SK=TIMESTAMP#AGENT`).
- Discovery-tier refresh: every 30 minutes, active 4:00am–8:00pm ET, paused 8:00pm–4:00am ET (spec §7).
- Chat grounding is structured DynamoDB reads + the process-history MCP tool — no vector DB (spec §4.6).
- Spec §10's "bounded retries per agent node, then graceful termination" is satisfied at two layers, not by a bespoke retry wrapper on every LLM call: transient Bedrock failures (throttling, 5xx) are retried by boto3/botocore's default retry config underneath `ChatBedrockConverse`; anything that still fails is caught by Task 24's per-symbol `try/except` in `scheduler_tick`, which is the graceful-termination boundary — that symbol's last good cached output stays visible and the rest of the watchlist proceeds. The Risk agent (Task 20) additionally layers its own bounded retry on top of this because its failure mode (a schema violation, not a transport error) is application-level, not something botocore's retries would ever catch.

---

## Phase A — Repo Foundations

### Task 1: Monorepo scaffolding and local dev environment

**Files:**
- Create: `services/mcp-server/`, `services/scheduler/`, `services/api-backend/` (each with `src/`, `tests/unit/`, `tests/integration/`, `pyproject.toml`, `Dockerfile`, `README.md`)
- Create: `frontend/` (placeholder, filled in Phase I)
- Create: `infra/terraform/`, `infra/k8s/helm/`, `infra/k8s/argocd/` (placeholders, filled in Phases K/L)
- Create: `monitoring/prometheus/`, `monitoring/grafana/` (placeholders, filled in Phase N)
- Create: `.github/workflows/` (placeholder, filled in Phase M)
- Create: `docker-compose.yaml`
- Create: `.gitignore`
- Create: `Makefile`

**Interfaces:**
- Produces: `docker-compose.yaml` service names `dynamodb-local`, `mcp-server`, `scheduler`, `api-backend`, `frontend` — every later task's Dockerfile and docker-compose wiring must match these exact service names.

- [ ] **Step 1: Create the directory tree**

```bash
mkdir -p services/mcp-server/src/{tools,clients} services/mcp-server/tests/{unit,integration}
mkdir -p services/scheduler/src/{rate_limit,graph} services/scheduler/tests/{unit,integration}
mkdir -p services/api-backend/src/{routers,chat} services/api-backend/tests/{unit,integration}
mkdir -p frontend/src/{components,hooks,api}
mkdir -p infra/terraform/{modules,envs/dev,envs/prod}
mkdir -p infra/k8s/helm/{frontend,api-backend,scheduler,mcp-server}
mkdir -p infra/k8s/argocd/applications
mkdir -p monitoring/prometheus/rules monitoring/grafana/dashboards
mkdir -p .github/workflows
```

- [ ] **Step 2: Write each Python service's `pyproject.toml`**

```toml
# services/mcp-server/pyproject.toml (identical pattern for scheduler, api-backend — change [project.name])
[project]
name = "mcp-server"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.2.0",
    "boto3>=1.35",
    "httpx>=0.27",
    "pydantic>=2.9",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "freezegun>=1.5", "moto[dynamodb,s3]>=5.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: Write the root `docker-compose.yaml`**

```yaml
services:
  dynamodb-local:
    image: amazon/dynamodb-local:2.5.4
    ports: ["8000:8000"]
    command: ["-jar", "DynamoDBLocal.jar", "-inMemory", "-sharedDb"]

  mcp-server:
    build: ./services/mcp-server
    env_file: [.env]
    environment:
      DYNAMODB_ENDPOINT: http://dynamodb-local:8000
    ports: ["8001:8001"]
    depends_on: [dynamodb-local]

  scheduler:
    build: ./services/scheduler
    env_file: [.env]
    environment:
      DYNAMODB_ENDPOINT: http://dynamodb-local:8000
      MCP_SERVER_URL: http://mcp-server:8001
    ports: ["8002:8002"]
    depends_on: [dynamodb-local, mcp-server]

  api-backend:
    build: ./services/api-backend
    env_file: [.env]
    environment:
      DYNAMODB_ENDPOINT: http://dynamodb-local:8000
      MCP_SERVER_URL: http://mcp-server:8001
    ports: ["8000:8080"]
    depends_on: [dynamodb-local, mcp-server]

  frontend:
    build: ./frontend
    ports: ["3000:80"]
    depends_on: [api-backend]
```

- [ ] **Step 4: Write `.gitignore` and `Makefile`**

```gitignore
__pycache__/
*.pyc
.venv/
node_modules/
dist/
.env
.terraform/
*.tfstate*
```

```makefile
.PHONY: up down test-mcp test-scheduler test-api
up:
	docker compose up --build
down:
	docker compose down -v
test-mcp:
	cd services/mcp-server && pytest
test-scheduler:
	cd services/scheduler && pytest
test-api:
	cd services/api-backend && pytest
```

- [ ] **Step 5: Verify the compose file is well-formed**

Run: `docker compose config --quiet`
Expected: no output, exit code 0 (services aren't buildable yet — that's fine, later tasks add real Dockerfiles/source).

- [ ] **Step 6: Commit**

```bash
git add services frontend infra monitoring .github docker-compose.yaml .gitignore Makefile
git commit -m "chore: scaffold monorepo layout and local dev compose file"
```

### Task 2: DynamoDB table schemas and local table bootstrap

**Files:**
- Create: `services/mcp-server/src/dynamo_schema.py`
- Create: `scripts/create_local_tables.py`
- Test: `services/mcp-server/tests/unit/test_dynamo_schema.py`

**Interfaces:**
- Produces: `TABLE_DEFINITIONS: dict[str, dict]` — a dict keyed by logical table name (`"ToolResults"`, `"AgentOutputs"`, `"ProcessHistory"`) each mapping to a `boto3` `create_table`-shaped kwargs dict (`TableName`, `KeySchema`, `AttributeDefinitions`, `BillingMode`). Every later task that creates a DynamoDB client (mcp-server, scheduler, api-backend, Terraform) imports table names from here rather than hardcoding strings.

- [ ] **Step 1: Write the failing test**

```python
# services/mcp-server/tests/unit/test_dynamo_schema.py
from src.dynamo_schema import TABLE_DEFINITIONS

def test_tool_results_key_schema():
    t = TABLE_DEFINITIONS["ToolResults"]
    assert t["KeySchema"] == [{"AttributeName": "pk", "KeyType": "HASH"}]

def test_agent_outputs_key_schema():
    t = TABLE_DEFINITIONS["AgentOutputs"]
    assert t["KeySchema"] == [
        {"AttributeName": "symbol", "KeyType": "HASH"},
        {"AttributeName": "agent_name", "KeyType": "RANGE"},
    ]

def test_process_history_key_schema():
    t = TABLE_DEFINITIONS["ProcessHistory"]
    assert t["KeySchema"] == [
        {"AttributeName": "symbol", "KeyType": "HASH"},
        {"AttributeName": "sk", "KeyType": "RANGE"},
    ]

def test_all_tables_use_pay_per_request():
    for name, t in TABLE_DEFINITIONS.items():
        assert t["BillingMode"] == "PAY_PER_REQUEST", name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/mcp-server && pytest tests/unit/test_dynamo_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.dynamo_schema'`

- [ ] **Step 3: Write the implementation**

```python
# services/mcp-server/src/dynamo_schema.py
TABLE_DEFINITIONS: dict[str, dict] = {
    "ToolResults": {
        "TableName": "ToolResults",
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}],
        "BillingMode": "PAY_PER_REQUEST",
    },
    "AgentOutputs": {
        "TableName": "AgentOutputs",
        "KeySchema": [
            {"AttributeName": "symbol", "KeyType": "HASH"},
            {"AttributeName": "agent_name", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "symbol", "AttributeType": "S"},
            {"AttributeName": "agent_name", "AttributeType": "S"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
    "ProcessHistory": {
        "TableName": "ProcessHistory",
        "KeySchema": [
            {"AttributeName": "symbol", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "symbol", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        "BillingMode": "PAY_PER_REQUEST",
    },
}
```

Note: `ToolResults`' native TTL attribute (`expires_at`, spec §6) is enabled via `update_time_to_live`, not `create_table` kwargs — that call is added in Task 2's bootstrap script below, and mirrored in the Terraform `aws_dynamodb_table` resource in Task 47.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/mcp-server && pytest tests/unit/test_dynamo_schema.py -v`
Expected: 4 passed

- [ ] **Step 5: Write the local bootstrap script**

```python
# scripts/create_local_tables.py
import boto3
import sys
sys.path.insert(0, "services/mcp-server")
from src.dynamo_schema import TABLE_DEFINITIONS

def main():
    client = boto3.client(
        "dynamodb", endpoint_url="http://localhost:8000",
        region_name="us-east-1", aws_access_key_id="local", aws_secret_access_key="local",
    )
    existing = set(client.list_tables()["TableNames"])
    for name, definition in TABLE_DEFINITIONS.items():
        if name in existing:
            print(f"{name}: already exists, skipping")
            continue
        client.create_table(**definition)
        client.get_waiter("table_exists").wait(TableName=name)
        if name == "ToolResults":
            client.update_time_to_live(
                TableName=name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
            )
        print(f"{name}: created")

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Verify against the running local DynamoDB**

Run: `docker compose up -d dynamodb-local && python scripts/create_local_tables.py`
Expected: prints `ToolResults: created`, `AgentOutputs: created`, `ProcessHistory: created`

- [ ] **Step 7: Commit**

```bash
git add services/mcp-server/src/dynamo_schema.py services/mcp-server/tests/unit/test_dynamo_schema.py scripts/create_local_tables.py
git commit -m "feat: define DynamoDB table schemas and local bootstrap script"
```

---

## Phase B — Deterministic Core (no LLM, no mocking needed)

### Task 3: Manager scoring formula (pure functions)

This is the system's most important deterministic component (spec §4.5.1) — zero external dependencies, so it's testable with real inputs and no mocking at all.

**Files:**
- Create: `services/mcp-server/src/tools/scoring.py`
- Test: `services/mcp-server/tests/unit/test_scoring.py`

**Interfaces:**
- Produces: `Claim` (TypedDict: `strength: Literal["strong","moderate","weak"]`, `corroborated: bool`, `flagged_unreliable: bool`, `rebutted_undefended: bool`, `source_type: Literal["news","volume","other"]`, `news_hours_old: float | None`, `news_is_primary_entity: bool | None`, `volume_ratio: float | None`, `avg_volume: float | None`), `score_claim(claim: Claim) -> float`, `compute_verdict(bull_claims: list[Claim], bear_claims: list[Claim], risk_level: Literal["low","medium","high"]) -> Verdict`, `Verdict` (TypedDict: `net_score: float`, `confidence: float`, `label: str`). Task 12 (the MCP scoring tool) imports `compute_verdict` directly.

- [ ] **Step 1: Write the failing tests for per-claim scoring**

```python
# services/mcp-server/tests/unit/test_scoring.py
from src.tools.scoring import score_claim, compute_verdict

def test_base_strength_values():
    strong = score_claim({"strength": "strong", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    moderate = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    weak = score_claim({"strength": "weak", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    assert strong == 3.0
    assert moderate == 2.0
    assert weak == 1.0

def test_corroboration_bonus_multiplies_by_1_5():
    base = score_claim({"strength": "strong", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    corroborated = score_claim({"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    assert corroborated == base * 1.5

def test_unreliable_data_penalty_halves_score():
    base = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    flagged = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": True, "rebutted_undefended": False, "source_type": "other"})
    assert flagged == base * 0.5

def test_rebutted_undefended_penalty_quarters_score():
    base = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"})
    rebutted = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": True, "source_type": "other"})
    assert rebutted == base * 0.25

def test_penalties_and_bonus_compose_multiplicatively():
    claim = {"strength": "strong", "corroborated": True, "flagged_unreliable": True, "rebutted_undefended": False, "source_type": "other"}
    assert score_claim(claim) == 3.0 * 1.5 * 0.5

def test_news_freshness_decays_over_48_hours():
    fresh = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": 0, "news_is_primary_entity": True})
    stale = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": 48, "news_is_primary_entity": True})
    assert fresh > stale
    assert stale == 2.0 * 0.5 * 1.2  # floor multiplier 0.5, primary-entity multiplier 1.2

def test_news_non_primary_entity_discounted():
    primary = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": 0, "news_is_primary_entity": True})
    mentioned = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "news", "news_hours_old": 0, "news_is_primary_entity": False})
    assert mentioned == primary / 1.2 * 0.8

def test_volume_extremity_is_log_compressed_and_liquidity_gated():
    liquid = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "volume", "volume_ratio": 10.0, "avg_volume": 5_000_000})
    illiquid = score_claim({"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "volume", "volume_ratio": 10.0, "avg_volume": 10_000})
    assert liquid > 2.0  # boosted
    assert illiquid == 2.0  # liquidity gate: below 100k avg volume, no boost applied
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/mcp-server && pytest tests/unit/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.tools.scoring'`

- [ ] **Step 3: Write `score_claim`**

```python
# services/mcp-server/src/tools/scoring.py
import math
from typing import Literal, TypedDict

class Claim(TypedDict, total=False):
    strength: Literal["strong", "moderate", "weak"]
    corroborated: bool
    flagged_unreliable: bool
    rebutted_undefended: bool
    source_type: Literal["news", "volume", "other"]
    news_hours_old: float | None
    news_is_primary_entity: bool | None
    volume_ratio: float | None
    avg_volume: float | None

class Verdict(TypedDict):
    net_score: float
    confidence: float
    label: str

_BASE_STRENGTH = {"strong": 3.0, "moderate": 2.0, "weak": 1.0}
_CORROBORATION_BONUS = 1.5
_UNRELIABLE_PENALTY = 0.5
_REBUTTED_UNDEFENDED_PENALTY = 0.25
_NEWS_FRESHNESS_FLOOR = 0.5
_NEWS_FRESHNESS_WINDOW_HOURS = 48.0
_NEWS_PRIMARY_ENTITY_MULT = 1.2
_NEWS_MENTIONED_ENTITY_MULT = 0.8
_VOLUME_LIQUIDITY_FLOOR = 100_000
_VOLUME_MAX_BOOST = 0.5

def score_claim(claim: Claim) -> float:
    score = _BASE_STRENGTH[claim["strength"]]
    if claim.get("corroborated"):
        score *= _CORROBORATION_BONUS
    if claim.get("flagged_unreliable"):
        score *= _UNRELIABLE_PENALTY
    if claim.get("rebutted_undefended"):
        score *= _REBUTTED_UNDEFENDED_PENALTY

    if claim.get("source_type") == "news":
        hours_old = claim.get("news_hours_old") or 0.0
        decay = max(_NEWS_FRESHNESS_FLOOR, 1.0 - hours_old / _NEWS_FRESHNESS_WINDOW_HOURS)
        score *= decay
        score *= _NEWS_PRIMARY_ENTITY_MULT if claim.get("news_is_primary_entity") else _NEWS_MENTIONED_ENTITY_MULT

    if claim.get("source_type") == "volume":
        avg_volume = claim.get("avg_volume") or 0.0
        if avg_volume >= _VOLUME_LIQUIDITY_FLOOR:
            ratio = claim.get("volume_ratio") or 1.0
            boost = min(_VOLUME_MAX_BOOST, math.log10(max(ratio, 1.0)))
            score *= 1.0 + boost

    return score
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/mcp-server && pytest tests/unit/test_scoring.py -v`
Expected: 8 passed

- [ ] **Step 5: Write the failing tests for `compute_verdict`**

```python
# append to services/mcp-server/tests/unit/test_scoring.py

def _claim(strength="moderate", **overrides):
    base = {"strength": strength, "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"}
    base.update(overrides)
    return base

def test_net_score_positive_when_bull_dominates():
    verdict = compute_verdict(bull_claims=[_claim("strong"), _claim("strong")], bear_claims=[_claim("weak")], risk_level="low")
    assert verdict["net_score"] > 0

def test_net_score_negative_when_bear_dominates():
    verdict = compute_verdict(bull_claims=[_claim("weak")], bear_claims=[_claim("strong"), _claim("strong")], risk_level="low")
    assert verdict["net_score"] < 0

def test_net_score_zero_with_no_claims():
    verdict = compute_verdict(bull_claims=[], bear_claims=[], risk_level="low")
    assert verdict["net_score"] == 0.0
    assert verdict["confidence"] == 0.0

def test_net_score_bounded_at_100():
    verdict = compute_verdict(bull_claims=[_claim("strong")] * 10, bear_claims=[], risk_level="low")
    assert verdict["net_score"] == 100.0

def test_risk_adjustment_scales_confidence_never_flips_direction():
    low = compute_verdict(bull_claims=[_claim("strong"), _claim("strong")], bear_claims=[_claim("weak")], risk_level="low")
    high = compute_verdict(bull_claims=[_claim("strong"), _claim("strong")], bear_claims=[_claim("weak")], risk_level="high")
    assert low["confidence"] > high["confidence"]
    assert (low["net_score"] > 0) == (high["net_score"] > 0)

def test_label_reflects_direction_and_confidence():
    verdict = compute_verdict(bull_claims=[_claim("strong"), _claim("strong"), _claim("strong")], bear_claims=[], risk_level="low")
    assert verdict["label"].startswith("Bullish")

    verdict = compute_verdict(bull_claims=[], bear_claims=[_claim("strong"), _claim("strong"), _claim("strong")], risk_level="low")
    assert verdict["label"].startswith("Bearish")
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd services/mcp-server && pytest tests/unit/test_scoring.py -v`
Expected: FAIL — `compute_verdict` not defined

- [ ] **Step 7: Write `compute_verdict`**

```python
# append to services/mcp-server/src/tools/scoring.py

_RISK_CONFIDENCE_MULT = {"low": 1.0, "medium": 0.75, "high": 0.5}

def compute_verdict(bull_claims: list[Claim], bear_claims: list[Claim], risk_level: Literal["low", "medium", "high"]) -> Verdict:
    bull_total = sum(score_claim(c) for c in bull_claims)
    bear_total = sum(score_claim(c) for c in bear_claims)
    denom = bull_total + bear_total

    if denom == 0:
        return {"net_score": 0.0, "confidence": 0.0, "label": "Neutral, no confidence"}

    net_score = max(-100.0, min(100.0, 100.0 * (bull_total - bear_total) / denom))

    flagged_or_rebutted = sum(
        1 for c in bull_claims + bear_claims
        if c.get("flagged_unreliable") or c.get("rebutted_undefended")
    )
    corroborated = sum(1 for c in bull_claims + bear_claims if c.get("corroborated"))
    total_claims = len(bull_claims) + len(bear_claims)

    base_confidence = abs(net_score)
    penalty = min(40.0, flagged_or_rebutted * 8.0)
    boost = min(20.0, corroborated * 5.0)
    confidence = max(0.0, min(100.0, base_confidence - penalty + boost))
    confidence *= _RISK_CONFIDENCE_MULT[risk_level]

    direction = "Bullish" if net_score > 0 else "Bearish" if net_score < 0 else "Neutral"
    tier = "high" if confidence >= 70 else "moderate" if confidence >= 40 else "low"
    label = f"{direction}, {tier} confidence"

    return {"net_score": net_score, "confidence": confidence, "label": label}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd services/mcp-server && pytest tests/unit/test_scoring.py -v`
Expected: 14 passed

- [ ] **Step 9: Commit**

```bash
git add services/mcp-server/src/tools/scoring.py services/mcp-server/tests/unit/test_scoring.py
git commit -m "feat: implement manager scoring formula with documented constants"
```

### Task 4: Sliding-window rate limiter and daily-cap scheduler

Two of the five per-provider strategies from spec §7: Finnhub/FRED use a sliding-window limiter (per-minute cap); Marketaux/FMP use a daily-cap scheduler with a rotation. Both live in the Scheduler service since only it calls providers live.

**Files:**
- Create: `services/scheduler/src/rate_limit/sliding_window.py`
- Create: `services/scheduler/src/rate_limit/daily_cap.py`
- Test: `services/scheduler/tests/unit/test_sliding_window.py`
- Test: `services/scheduler/tests/unit/test_daily_cap.py`

**Interfaces:**
- Produces: `SlidingWindowLimiter(max_calls: int, window_seconds: float)` with method `allow(now: datetime) -> bool` (records the call if allowed); `DailyCapScheduler(daily_cap: int, safety_margin: int)` with methods `allow(now: datetime) -> bool` and `remaining(now: datetime) -> int`, resetting its count at UTC midnight. Task 16 (Input Data Agent) and Task 15 (schedule config) import both directly.

- [ ] **Step 1: Write the failing tests for the sliding-window limiter**

```python
# services/scheduler/tests/unit/test_sliding_window.py
from datetime import datetime, timedelta
from src.rate_limit.sliding_window import SlidingWindowLimiter

def test_allows_calls_up_to_max_within_window():
    limiter = SlidingWindowLimiter(max_calls=3, window_seconds=60)
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert limiter.allow(now) is True
    assert limiter.allow(now) is True
    assert limiter.allow(now) is True
    assert limiter.allow(now) is False

def test_old_calls_fall_out_of_window():
    limiter = SlidingWindowLimiter(max_calls=1, window_seconds=60)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    assert limiter.allow(t0) is True
    assert limiter.allow(t0 + timedelta(seconds=30)) is False
    assert limiter.allow(t0 + timedelta(seconds=61)) is True

def test_disallowed_calls_are_not_recorded():
    limiter = SlidingWindowLimiter(max_calls=1, window_seconds=60)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    limiter.allow(t0)
    limiter.allow(t0 + timedelta(seconds=1))  # rejected, must not count
    assert limiter.allow(t0 + timedelta(seconds=61)) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_sliding_window.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/rate_limit/sliding_window.py
from collections import deque
from datetime import datetime, timedelta

class SlidingWindowLimiter:
    def __init__(self, max_calls: int, window_seconds: float):
        self._max_calls = max_calls
        self._window = timedelta(seconds=window_seconds)
        self._calls: deque[datetime] = deque()

    def allow(self, now: datetime) -> bool:
        cutoff = now - self._window
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()
        if len(self._calls) >= self._max_calls:
            return False
        self._calls.append(now)
        return True
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_sliding_window.py -v`
Expected: 3 passed

- [ ] **Step 5: Write the failing tests for the daily-cap scheduler**

```python
# services/scheduler/tests/unit/test_daily_cap.py
from datetime import datetime, timezone
from src.rate_limit.daily_cap import DailyCapScheduler

def test_allows_up_to_cap_minus_safety_margin():
    sched = DailyCapScheduler(daily_cap=100, safety_margin=10)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    for _ in range(90):
        assert sched.allow(now) is True
    assert sched.allow(now) is False  # 90 used, cap is 100, margin 10 -> budget 90

def test_remaining_reflects_budget_used():
    sched = DailyCapScheduler(daily_cap=100, safety_margin=10)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert sched.remaining(now) == 90
    sched.allow(now)
    assert sched.remaining(now) == 89

def test_resets_at_utc_midnight():
    sched = DailyCapScheduler(daily_cap=1, safety_margin=0)
    day1 = datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc)
    day2 = datetime(2026, 1, 2, 0, 1, tzinfo=timezone.utc)
    assert sched.allow(day1) is True
    assert sched.allow(day1) is False
    assert sched.allow(day2) is True
```

- [ ] **Step 6: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_daily_cap.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 7: Implement**

```python
# services/scheduler/src/rate_limit/daily_cap.py
from datetime import datetime

class DailyCapScheduler:
    def __init__(self, daily_cap: int, safety_margin: int):
        self._budget = daily_cap - safety_margin
        self._used = 0
        self._current_day: str | None = None

    def _roll_if_new_day(self, now: datetime) -> None:
        day_key = now.date().isoformat()
        if day_key != self._current_day:
            self._current_day = day_key
            self._used = 0

    def allow(self, now: datetime) -> bool:
        self._roll_if_new_day(now)
        if self._used >= self._budget:
            return False
        self._used += 1
        return True

    def remaining(self, now: datetime) -> int:
        self._roll_if_new_day(now)
        return self._budget - self._used
```

- [ ] **Step 8: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_daily_cap.py -v`
Expected: 3 passed

- [ ] **Step 9: Commit**

```bash
git add services/scheduler/src/rate_limit services/scheduler/tests/unit/test_sliding_window.py services/scheduler/tests/unit/test_daily_cap.py
git commit -m "feat: add sliding-window and daily-cap rate limiters"
```

### Task 5: Circuit breaker for TradingView-backed tools

Shared by both third-party MCP servers and the discovery tier (spec §7, §10) — a fixed failure threshold trips it, then it stays open for a cooldown window and reports "stale" instead of calling.

**Files:**
- Create: `services/scheduler/src/rate_limit/circuit_breaker.py`
- Test: `services/scheduler/tests/unit/test_circuit_breaker.py`

**Interfaces:**
- Produces: `CircuitBreaker(failure_threshold: int, cooldown_seconds: float)` with methods `allow_call(now: datetime) -> bool`, `record_success(now: datetime) -> None`, `record_failure(now: datetime) -> None`, property `state: Literal["closed","open","half_open"]`. Task 14's `call_tool` wraps every `"tradingview"`/`"stock_scanner"` call with this one shared instance, so both third-party servers share it, per spec §7.

- [ ] **Step 1: Write the failing tests**

```python
# services/scheduler/tests/unit/test_circuit_breaker.py
from datetime import datetime, timedelta
from src.rate_limit.circuit_breaker import CircuitBreaker

def test_starts_closed_and_allows_calls():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert cb.state == "closed"
    assert cb.allow_call(now) is True

def test_trips_open_after_threshold_consecutive_failures():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    now = datetime(2026, 1, 1, 12, 0, 0)
    cb.record_failure(now)
    cb.record_failure(now)
    assert cb.state == "closed"
    cb.record_failure(now)
    assert cb.state == "open"
    assert cb.allow_call(now) is False

def test_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    now = datetime(2026, 1, 1, 12, 0, 0)
    cb.record_failure(now)
    cb.record_failure(now)
    cb.record_success(now)
    cb.record_failure(now)
    cb.record_failure(now)
    assert cb.state == "closed"  # only 2 consecutive since the success reset it

def test_moves_to_half_open_after_cooldown_then_closes_on_success():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    cb.record_failure(t0)
    assert cb.state == "open"
    assert cb.allow_call(t0 + timedelta(seconds=30)) is False  # still cooling down
    assert cb.allow_call(t0 + timedelta(seconds=61)) is True  # half-open, allows a probe call
    assert cb.state == "half_open"
    cb.record_success(t0 + timedelta(seconds=61))
    assert cb.state == "closed"

def test_half_open_failure_reopens_and_restarts_cooldown():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    cb.record_failure(t0)
    cb.allow_call(t0 + timedelta(seconds=61))  # half-open probe
    cb.record_failure(t0 + timedelta(seconds=61))
    assert cb.state == "open"
    assert cb.allow_call(t0 + timedelta(seconds=90)) is False  # cooldown restarted from t0+61
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_circuit_breaker.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/rate_limit/circuit_breaker.py
from datetime import datetime, timedelta
from typing import Literal

class CircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_seconds: float):
        self._threshold = failure_threshold
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._consecutive_failures = 0
        self._state: Literal["closed", "open", "half_open"] = "closed"
        self._opened_at: datetime | None = None

    @property
    def state(self) -> Literal["closed", "open", "half_open"]:
        return self._state

    def allow_call(self, now: datetime) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            assert self._opened_at is not None
            if now - self._opened_at >= self._cooldown:
                self._state = "half_open"
                return True
            return False
        return True  # half_open: allow the single probe call

    def record_success(self, now: datetime) -> None:
        self._consecutive_failures = 0
        self._state = "closed"
        self._opened_at = None

    def record_failure(self, now: datetime) -> None:
        self._consecutive_failures += 1
        if self._state == "half_open" or self._consecutive_failures >= self._threshold:
            self._state = "open"
            self._opened_at = now
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_circuit_breaker.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add services/scheduler/src/rate_limit/circuit_breaker.py services/scheduler/tests/unit/test_circuit_breaker.py
git commit -m "feat: add shared circuit breaker for TradingView-backed tools"
```

---

## Phase C — Shared Persistence Layer

All three Python services (MCP server, Scheduler, API Backend) read or write the same three DynamoDB tables (spec §6). Rather than duplicating that logic three times, it lives in one shared package all three services depend on.

### Task 6: Shared `common` package — DynamoDB + S3-offload helpers

**Files:**
- Create: `packages/common/pyproject.toml`
- Create: `packages/common/common/dynamo.py`
- Test: `packages/common/tests/test_dynamo.py`
- Modify: `services/mcp-server/pyproject.toml`, `services/scheduler/pyproject.toml`, `services/api-backend/pyproject.toml` (add `common` as a local path dependency)

**Interfaces:**
- Produces: `read_tool_result(pk: str) -> dict | None`, `write_tool_result(pk: str, payload: dict, ttl_seconds: int) -> None`, `read_agent_output(symbol: str, agent_name: str) -> dict | None`, `write_agent_output(symbol: str, agent_name: str, payload: dict) -> None`, `append_process_history(symbol: str, agent: str, reason: str, status: str, timestamp: datetime) -> None`, `query_process_history(symbol: str, since: datetime | None = None) -> list[dict]`, `record_fetch_attempt(pk: str, timestamp: datetime) -> None`, `get_last_fetch_attempt(pk: str) -> datetime | None`. Task 12 (the process-history MCP tool), Task 16 (Input Data Agent, all of these including the last two for cadence enforcement), and Tasks 27/28/29/30 (API Backend's watchlist, dashboard, stream, and chat endpoints) all import from `common.dynamo`.
- Consumes: table names `"ToolResults"`, `"AgentOutputs"`, `"ProcessHistory"` (must match Task 2's `TABLE_DEFINITIONS` keys exactly), env vars `DYNAMODB_ENDPOINT` (optional, for local), `TOOL_PAYLOADS_BUCKET`, `AWS_REGION`.

- [ ] **Step 1: Write `packages/common/pyproject.toml`**

```toml
[project]
name = "common"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["boto3>=1.35"]

[project.optional-dependencies]
dev = ["pytest>=8.3", "moto[dynamodb,s3]>=5.0", "freezegun>=1.5"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing tests for `ToolResults` (inline vs. S3-offloaded)**

```python
# packages/common/tests/test_dynamo.py
import json
import boto3
import pytest
from moto import mock_aws
from datetime import datetime, timezone
from common.dynamo import (
    read_tool_result, write_tool_result,
    read_agent_output, write_agent_output,
    append_process_history, query_process_history,
    record_fetch_attempt, get_last_fetch_attempt,
    ensure_tables_for_test,
)

@pytest.fixture
def aws():
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").meta  # trigger client init
        ensure_tables_for_test()
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="tool-payloads-test")
        yield

def test_small_payload_stored_inline(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    write_tool_result("AAPL#Quote", {"price": 150}, ttl_seconds=3600)
    result = read_tool_result("AAPL#Quote")
    assert result == {"price": 150}

def test_oversized_payload_offloaded_to_s3(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    big_payload = {"filing_text": "x" * 400_000}  # exceeds 300KB threshold
    write_tool_result("AAPL#EdgarFiling", big_payload, ttl_seconds=3600)
    result = read_tool_result("AAPL#EdgarFiling")
    assert result == big_payload  # transparently resolved on read

def test_missing_tool_result_returns_none(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    assert read_tool_result("MSFT#Quote") is None

def test_agent_output_roundtrip(aws):
    write_agent_output("AAPL", "Fundamentals", {"strength": "strong"})
    assert read_agent_output("AAPL", "Fundamentals") == {"strength": "strong"}
    assert read_agent_output("AAPL", "Technical") is None

def test_process_history_append_and_query_ordered(aws):
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)
    append_process_history("AAPL", "Sentiment", reason="news_cascade", status="started", timestamp=t1)
    append_process_history("AAPL", "Sentiment", reason="news_cascade", status="finished", timestamp=t2)
    entries = query_process_history("AAPL")
    assert [e["status"] for e in entries] == ["started", "finished"]

def test_process_history_query_since_filters_older_entries(aws):
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=t1)
    append_process_history("AAPL", "Risk", reason="scheduled", status="finished", timestamp=t2)
    entries = query_process_history("AAPL", since=datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc))
    assert len(entries) == 1
    assert entries[0]["timestamp"] == t2.isoformat()

def test_last_fetch_attempt_is_none_before_any_attempt(aws):
    assert get_last_fetch_attempt("AAPL#finnhub_company_profile") is None

def test_record_and_read_back_last_fetch_attempt(aws):
    t = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    record_fetch_attempt("AAPL#finnhub_company_profile", t)
    assert get_last_fetch_attempt("AAPL#finnhub_company_profile") == t

def test_recording_an_attempt_does_not_disturb_the_actual_tool_result(aws, monkeypatch):
    monkeypatch.setenv("TOOL_PAYLOADS_BUCKET", "tool-payloads-test")
    write_tool_result("AAPL#Quote", {"price": 150}, ttl_seconds=3600)
    record_fetch_attempt("AAPL#Quote", datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    assert read_tool_result("AAPL#Quote") == {"price": 150}
```

- [ ] **Step 3: Run to verify failure**

Run: `cd packages/common && pytest -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common.dynamo'`

- [ ] **Step 4: Implement**

```python
# packages/common/common/dynamo.py
import json
import os
import uuid
from datetime import datetime, timezone

import boto3

_OFFLOAD_THRESHOLD_BYTES = 300_000

def _dynamo_resource():
    kwargs = {"region_name": os.environ.get("AWS_REGION", "us-east-1")}
    if endpoint := os.environ.get("DYNAMODB_ENDPOINT"):
        kwargs["endpoint_url"] = endpoint
    return boto3.resource("dynamodb", **kwargs)

def _s3_client():
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))

def ensure_tables_for_test() -> None:
    """Test-only helper: creates all three tables against the current (mocked) DynamoDB."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "mcp-server"))
    from src.dynamo_schema import TABLE_DEFINITIONS
    client = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    for definition in TABLE_DEFINITIONS.values():
        client.create_table(**definition)

def write_tool_result(pk: str, payload: dict, ttl_seconds: int) -> None:
    table = _dynamo_resource().Table("ToolResults")
    expires_at = int(datetime.now(timezone.utc).timestamp()) + ttl_seconds
    serialized = json.dumps(payload)
    if len(serialized.encode()) > _OFFLOAD_THRESHOLD_BYTES:
        bucket = os.environ["TOOL_PAYLOADS_BUCKET"]
        key = f"{pk}/{uuid.uuid4()}.json"
        _s3_client().put_object(Bucket=bucket, Key=key, Body=serialized.encode())
        table.put_item(Item={"pk": pk, "s3_bucket": bucket, "s3_key": key, "expires_at": expires_at})
    else:
        table.put_item(Item={"pk": pk, "payload": serialized, "expires_at": expires_at})

def read_tool_result(pk: str) -> dict | None:
    table = _dynamo_resource().Table("ToolResults")
    item = table.get_item(Key={"pk": pk}).get("Item")
    if item is None:
        return None
    if "s3_key" in item:
        obj = _s3_client().get_object(Bucket=item["s3_bucket"], Key=item["s3_key"])
        return json.loads(obj["Body"].read())
    return json.loads(item["payload"])

def write_agent_output(symbol: str, agent_name: str, payload: dict) -> None:
    table = _dynamo_resource().Table("AgentOutputs")
    table.put_item(Item={
        "symbol": symbol, "agent_name": agent_name,
        "payload": json.dumps(payload),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

def read_agent_output(symbol: str, agent_name: str) -> dict | None:
    table = _dynamo_resource().Table("AgentOutputs")
    item = table.get_item(Key={"symbol": symbol, "agent_name": agent_name}).get("Item")
    return json.loads(item["payload"]) if item else None

def append_process_history(symbol: str, agent: str, reason: str, status: str, timestamp: datetime) -> None:
    table = _dynamo_resource().Table("ProcessHistory")
    sk = f"{timestamp.isoformat()}#{agent}"
    table.put_item(Item={
        "symbol": symbol, "sk": sk, "agent": agent,
        "reason": reason, "status": status, "timestamp": timestamp.isoformat(),
    })

def query_process_history(symbol: str, since: datetime | None = None) -> list[dict]:
    table = _dynamo_resource().Table("ProcessHistory")
    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("symbol").eq(symbol),
    )
    items = sorted(response["Items"], key=lambda i: i["sk"])
    if since is not None:
        items = [i for i in items if i["timestamp"] >= since.isoformat()]
    return items

_FETCH_ATTEMPT_TTL_SECONDS = 7 * 86400  # generous fixed window, independent of any tool's own cadence

def record_fetch_attempt(pk: str, timestamp: datetime) -> None:
    """Records that a *successful* live call was made for `pk`, independent of whether the
    fetched value actually changed. This is deliberately separate from write_tool_result,
    which only writes on a diff — cadence enforcement (Task 16's _is_due) needs "when did we
    last try" even when the value has been stable for a while and nothing gets rewritten."""
    table = _dynamo_resource().Table("ToolResults")
    expires_at = int(timestamp.timestamp()) + _FETCH_ATTEMPT_TTL_SECONDS
    table.put_item(Item={"pk": f"{pk}#LAST_ATTEMPT", "attempted_at": timestamp.isoformat(), "expires_at": expires_at})

def get_last_fetch_attempt(pk: str) -> datetime | None:
    table = _dynamo_resource().Table("ToolResults")
    item = table.get_item(Key={"pk": f"{pk}#LAST_ATTEMPT"}).get("Item")
    return datetime.fromisoformat(item["attempted_at"]) if item else None
```

- [ ] **Step 5: Run to verify pass**

Run: `cd packages/common && pytest -v`
Expected: 9 passed

- [ ] **Step 6: Wire `common` as a path dependency in each service**

```toml
# add to services/mcp-server/pyproject.toml, services/scheduler/pyproject.toml, services/api-backend/pyproject.toml
dependencies = [
    # ...existing deps...
    "common @ file:///../../packages/common",
]
```

Each service's Dockerfile (written in Tasks 13, 26, 31) must `COPY packages/common /packages/common` alongside its own service directory, since the path dependency is relative to the monorepo root.

- [ ] **Step 7: Commit**

```bash
git add packages/common services/mcp-server/pyproject.toml services/scheduler/pyproject.toml services/api-backend/pyproject.toml
git commit -m "feat: add shared common package for DynamoDB + S3-offload persistence"
```

---

## Phase D — Self-Built MCP Server (35 tools)

Tool wrappers are thin passthroughs to each provider's REST API — no caching or scheduling logic inside them. Caching/scheduling lives entirely in the Scheduler's Input Data Agent (Phase E), which decides *whether* to call a tool; the tool itself just calls it. Every provider client shares one small HTTP base class.

### Task 7: FastMCP app skeleton and shared HTTP client base

**Files:**
- Create: `services/mcp-server/src/clients/base.py`
- Create: `services/mcp-server/src/server.py`
- Test: `services/mcp-server/tests/unit/test_base_client.py`

**Interfaces:**
- Produces: `ProviderClient(base_url: str, api_key: str, api_key_param: str)` with async method `get(path: str, params: dict | None = None) -> dict`; `create_app() -> FastMCP` (returns the assembled server with all tool groups registered — Tasks 8–12 each add a `register_*_tools(app)` call inside it).

- [ ] **Step 1: Write the failing test**

```python
# services/mcp-server/tests/unit/test_base_client.py
import pytest
import respx
import httpx
from src.clients.base import ProviderClient

@pytest.mark.asyncio
@respx.mock
async def test_get_injects_api_key_as_query_param():
    route = respx.get("https://example.com/thing").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = ProviderClient(base_url="https://example.com", api_key="secret123", api_key_param="token")
    result = await client.get("/thing", {"symbol": "AAPL"})
    assert result == {"ok": True}
    assert route.calls.last.request.url.params["token"] == "secret123"
    assert route.calls.last.request.url.params["symbol"] == "AAPL"

@pytest.mark.asyncio
@respx.mock
async def test_get_raises_on_http_error():
    respx.get("https://example.com/bad").mock(return_value=httpx.Response(500))
    client = ProviderClient(base_url="https://example.com", api_key="k", api_key_param="token")
    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/bad")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/mcp-server && pytest tests/unit/test_base_client.py -v`
Expected: FAIL with `ModuleNotFoundError`. Add `respx>=0.21` and `pytest-asyncio>=0.24` to the `dev` extra in `services/mcp-server/pyproject.toml` first if not already present (added in Task 1).

- [ ] **Step 3: Implement**

```python
# services/mcp-server/src/clients/base.py
import httpx

class ProviderClient:
    def __init__(self, base_url: str, api_key: str, api_key_param: str):
        self._api_key = api_key
        self._api_key_param = api_key_param
        self._client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def get(self, path: str, params: dict | None = None) -> dict:
        query = dict(params or {})
        query[self._api_key_param] = self._api_key
        response = await self._client.get(path, params=query)
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/mcp-server && pytest tests/unit/test_base_client.py -v`
Expected: 2 passed

- [ ] **Step 5: Write the server skeleton**

```python
# services/mcp-server/src/server.py
from mcp.server.fastmcp import FastMCP

def create_app() -> FastMCP:
    app = FastMCP("stock-research-mcp-server")

    from .tools.finnhub_tools import register_finnhub_tools
    from .tools.fmp_tools import register_fmp_tools
    from .tools.fred_tools import register_fred_tools
    from .tools.marketaux_tools import register_marketaux_tools
    from .tools.scoring_tool import register_scoring_tool
    from .tools.process_history_tool import register_process_history_tool

    register_finnhub_tools(app)
    register_fmp_tools(app)
    register_fred_tools(app)
    register_marketaux_tools(app)
    register_scoring_tool(app)
    register_process_history_tool(app)

    return app

if __name__ == "__main__":
    create_app().run(transport="streamable-http")
```

This will fail to import until Tasks 8–12 create the six `register_*` modules — that's expected; each subsequent task makes one import resolve.

- [ ] **Step 6: Commit**

```bash
git add services/mcp-server/src/clients/base.py services/mcp-server/src/server.py services/mcp-server/tests/unit/test_base_client.py
git commit -m "feat: add MCP server skeleton and shared provider HTTP client base"
```

### Task 8: Finnhub tools (11)

**Files:**
- Create: `services/mcp-server/src/clients/finnhub_client.py`
- Create: `services/mcp-server/src/tools/finnhub_tools.py`
- Test: `services/mcp-server/tests/unit/test_finnhub_tools.py`

**Interfaces:**
- Consumes: `ProviderClient` (Task 7)
- Produces: `register_finnhub_tools(app: FastMCP) -> None`, registering tools named `finnhub_company_profile`, `finnhub_peers`, `finnhub_basic_financials`, `finnhub_earnings_calendar`, `finnhub_earnings_surprises`, `finnhub_insider_transactions`, `finnhub_insider_sentiment`, `finnhub_lobbying_data`, `finnhub_usa_spending`, `finnhub_company_news`, `finnhub_quote`.

- [ ] **Step 1: Write the failing tests (representative sample — full suite covers all 11)**

```python
# services/mcp-server/tests/unit/test_finnhub_tools.py
import pytest
import respx
import httpx
import os
from src.clients.finnhub_client import finnhub_client

@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

@pytest.mark.asyncio
@respx.mock
async def test_quote_calls_correct_endpoint_with_symbol():
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 150.0})
    )
    client = finnhub_client()
    result = await client.get("/quote", {"symbol": "AAPL"})
    assert result == {"c": 150.0}

@pytest.mark.asyncio
@respx.mock
async def test_company_news_passes_date_range():
    route = respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = finnhub_client()
    await client.get("/company-news", {"symbol": "AAPL", "from": "2026-01-01", "to": "2026-01-08"})
    assert route.calls.last.request.url.params["from"] == "2026-01-01"

@pytest.mark.asyncio
@respx.mock
async def test_insider_sentiment_endpoint():
    respx.get("https://finnhub.io/api/v1/stock/insider-sentiment").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = finnhub_client()
    result = await client.get("/stock/insider-sentiment", {"symbol": "AAPL"})
    assert result == {"data": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/mcp-server && pytest tests/unit/test_finnhub_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the client factory**

```python
# services/mcp-server/src/clients/finnhub_client.py
import os
from .base import ProviderClient

def finnhub_client() -> ProviderClient:
    return ProviderClient(
        base_url="https://finnhub.io/api/v1",
        api_key=os.environ["FINNHUB_API_KEY"],
        api_key_param="token",
    )
```

- [ ] **Step 4: Implement all 11 tools**

```python
# services/mcp-server/src/tools/finnhub_tools.py
from mcp.server.fastmcp import FastMCP
from ..clients.finnhub_client import finnhub_client

def register_finnhub_tools(app: FastMCP) -> None:
    client = finnhub_client()

    @app.tool()
    async def finnhub_company_profile(symbol: str) -> dict:
        """Company profile (name, industry, market cap, IPO date) for a stock symbol."""
        return await client.get("/stock/profile2", {"symbol": symbol})

    @app.tool()
    async def finnhub_peers(symbol: str) -> dict:
        """Peer companies in the same industry for a stock symbol."""
        return await client.get("/stock/peers", {"symbol": symbol})

    @app.tool()
    async def finnhub_basic_financials(symbol: str) -> dict:
        """Basic financial metrics (margins, ratios, per-share figures) for a stock symbol."""
        return await client.get("/stock/metric", {"symbol": symbol, "metric": "all"})

    @app.tool()
    async def finnhub_earnings_calendar(symbol: str) -> dict:
        """Upcoming and past earnings report dates for a stock symbol."""
        return await client.get("/calendar/earnings", {"symbol": symbol})

    @app.tool()
    async def finnhub_earnings_surprises(symbol: str) -> dict:
        """Historical EPS actual-vs-estimate surprises for a stock symbol."""
        return await client.get("/stock/earnings", {"symbol": symbol})

    @app.tool()
    async def finnhub_insider_transactions(symbol: str) -> dict:
        """Recent insider buy/sell transactions for a stock symbol."""
        return await client.get("/stock/insider-transactions", {"symbol": symbol})

    @app.tool()
    async def finnhub_insider_sentiment(symbol: str) -> dict:
        """Aggregate monthly insider sentiment (MSPR) for a stock symbol."""
        return await client.get("/stock/insider-sentiment", {"symbol": symbol})

    @app.tool()
    async def finnhub_lobbying_data(symbol: str) -> dict:
        """Corporate lobbying spend disclosures for a stock symbol."""
        return await client.get("/stock/lobbying", {"symbol": symbol})

    @app.tool()
    async def finnhub_usa_spending(symbol: str) -> dict:
        """US government contract spending records for a stock symbol."""
        return await client.get("/stock/usa-spending", {"symbol": symbol})

    @app.tool()
    async def finnhub_company_news(symbol: str, from_date: str, to_date: str) -> dict:
        """Company news articles for a stock symbol within a date range (YYYY-MM-DD)."""
        return await client.get("/company-news", {"symbol": symbol, "from": from_date, "to": to_date})

    @app.tool()
    async def finnhub_quote(symbol: str) -> dict:
        """Real-time quote: current price, change, high/low/open, previous close."""
        return await client.get("/quote", {"symbol": symbol})
```

- [ ] **Step 5: Run to verify pass**

Run: `cd services/mcp-server && pytest tests/unit/test_finnhub_tools.py -v`
Expected: 3 passed

- [ ] **Step 6: Verify the server now imports one step further**

Run: `cd services/mcp-server && python -c "from src.server import create_app"`
Expected: `ModuleNotFoundError: No module named 'src.tools.fmp_tools'` (progress — the Finnhub import resolved; FMP is next)

- [ ] **Step 7: Commit**

```bash
git add services/mcp-server/src/clients/finnhub_client.py services/mcp-server/src/tools/finnhub_tools.py services/mcp-server/tests/unit/test_finnhub_tools.py
git commit -m "feat: add Finnhub MCP tools (11)"
```

### Task 9: FMP tools (10)

**Files:**
- Create: `services/mcp-server/src/clients/fmp_client.py`
- Create: `services/mcp-server/src/tools/fmp_tools.py`
- Test: `services/mcp-server/tests/unit/test_fmp_tools.py`

**Interfaces:**
- Produces: `register_fmp_tools(app: FastMCP) -> None`, registering `fmp_income_statement`, `fmp_balance_sheet_statement`, `fmp_cash_flow_statement`, `fmp_financial_ratios`, `fmp_key_metrics`, `fmp_dcf_valuation`, `fmp_ratings_snapshot`, `fmp_dividends_calendar`, `fmp_stock_splits_calendar`, `fmp_economic_indicators`. Uses FMP's `/stable/` endpoint prefix (the legacy `/v3/` paths are retired).

- [ ] **Step 1: Write the failing tests**

```python
# services/mcp-server/tests/unit/test_fmp_tools.py
import pytest
import respx
import httpx
from src.clients.fmp_client import fmp_client

@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")

@pytest.mark.asyncio
@respx.mock
async def test_income_statement_uses_stable_prefix():
    route = respx.get("https://financialmodelingprep.com/stable/income-statement").mock(
        return_value=httpx.Response(200, json=[{"revenue": 1000}])
    )
    client = fmp_client()
    result = await client.get("/income-statement", {"symbol": "AAPL"})
    assert result == [{"revenue": 1000}]
    assert route.calls.last.request.url.params["apikey"] == "test-key"

@pytest.mark.asyncio
@respx.mock
async def test_dividends_calendar_is_global_no_symbol_required():
    respx.get("https://financialmodelingprep.com/stable/dividends-calendar").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = fmp_client()
    result = await client.get("/dividends-calendar", {"from": "2026-01-01", "to": "2026-01-31"})
    assert result == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/mcp-server && pytest tests/unit/test_fmp_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/mcp-server/src/clients/fmp_client.py
import os
from .base import ProviderClient

def fmp_client() -> ProviderClient:
    return ProviderClient(
        base_url="https://financialmodelingprep.com/stable",
        api_key=os.environ["FMP_API_KEY"],
        api_key_param="apikey",
    )
```

```python
# services/mcp-server/src/tools/fmp_tools.py
from mcp.server.fastmcp import FastMCP
from ..clients.fmp_client import fmp_client

def register_fmp_tools(app: FastMCP) -> None:
    client = fmp_client()

    @app.tool()
    async def fmp_income_statement(symbol: str) -> dict:
        """Annual income statement (revenue, expenses, net income) for a stock symbol."""
        return await client.get("/income-statement", {"symbol": symbol})

    @app.tool()
    async def fmp_balance_sheet_statement(symbol: str) -> dict:
        """Annual balance sheet (assets, liabilities, equity) for a stock symbol."""
        return await client.get("/balance-sheet-statement", {"symbol": symbol})

    @app.tool()
    async def fmp_cash_flow_statement(symbol: str) -> dict:
        """Annual cash flow statement for a stock symbol."""
        return await client.get("/cash-flow-statement", {"symbol": symbol})

    @app.tool()
    async def fmp_financial_ratios(symbol: str) -> dict:
        """Key financial ratios (P/E, ROE, debt/equity, etc.) for a stock symbol."""
        return await client.get("/ratios", {"symbol": symbol})

    @app.tool()
    async def fmp_key_metrics(symbol: str) -> dict:
        """Per-share and valuation key metrics for a stock symbol."""
        return await client.get("/key-metrics", {"symbol": symbol})

    @app.tool()
    async def fmp_dcf_valuation(symbol: str) -> dict:
        """Discounted cash flow fair-value estimate for a stock symbol."""
        return await client.get("/discounted-cash-flow", {"symbol": symbol})

    @app.tool()
    async def fmp_ratings_snapshot(symbol: str) -> dict:
        """Current analyst rating snapshot (buy/hold/sell composite) for a stock symbol."""
        return await client.get("/ratings-snapshot", {"symbol": symbol})

    @app.tool()
    async def fmp_dividends_calendar(from_date: str, to_date: str) -> dict:
        """Dividend calendar across all companies within a date range (YYYY-MM-DD). Global, not per-symbol."""
        return await client.get("/dividends-calendar", {"from": from_date, "to": to_date})

    @app.tool()
    async def fmp_stock_splits_calendar(from_date: str, to_date: str) -> dict:
        """Stock split calendar across all companies within a date range (YYYY-MM-DD). Global, not per-symbol."""
        return await client.get("/splits-calendar", {"from": from_date, "to": to_date})

    @app.tool()
    async def fmp_economic_indicators(indicator_name: str) -> dict:
        """Named macroeconomic indicator series (e.g. GDP, CPI) from FMP's economic indicators dataset."""
        return await client.get("/economic-indicators", {"name": indicator_name})
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/mcp-server && pytest tests/unit/test_fmp_tools.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add services/mcp-server/src/clients/fmp_client.py services/mcp-server/src/tools/fmp_tools.py services/mcp-server/tests/unit/test_fmp_tools.py
git commit -m "feat: add FMP MCP tools (10)"
```

### Task 10: FRED tools (11)

**Files:**
- Create: `services/mcp-server/src/clients/fred_client.py`
- Create: `services/mcp-server/src/tools/fred_tools.py`
- Test: `services/mcp-server/tests/unit/test_fred_tools.py`

**Interfaces:**
- Produces: `register_fred_tools(app: FastMCP) -> None`, registering `fred_federal_funds_rate`, `fred_10y_treasury_yield`, `fred_2y_treasury_yield`, `fred_cpi`, `fred_unemployment_rate`, `fred_nonfarm_payrolls`, `fred_real_gdp`, `fred_vix`, `fred_consumer_sentiment`, `fred_series_search`, `fred_release_calendar`. The first nine map directly to fixed FRED series IDs; the last two take free parameters.

- [ ] **Step 1: Write the failing tests**

```python
# services/mcp-server/tests/unit/test_fred_tools.py
import pytest
import respx
import httpx
from src.clients.fred_client import fred_client

@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")

@pytest.mark.asyncio
@respx.mock
async def test_series_observations_endpoint():
    route = respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json={"observations": []})
    )
    client = fred_client()
    result = await client.get("/series/observations", {"series_id": "DFF", "file_type": "json"})
    assert result == {"observations": []}
    assert route.calls.last.request.url.params["series_id"] == "DFF"

@pytest.mark.asyncio
@respx.mock
async def test_series_search_endpoint():
    respx.get("https://api.stlouisfed.org/fred/series/search").mock(
        return_value=httpx.Response(200, json={"seriess": []})
    )
    client = fred_client()
    result = await client.get("/series/search", {"search_text": "unemployment", "file_type": "json"})
    assert result == {"seriess": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/mcp-server && pytest tests/unit/test_fred_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/mcp-server/src/clients/fred_client.py
import os
from .base import ProviderClient

def fred_client() -> ProviderClient:
    return ProviderClient(
        base_url="https://api.stlouisfed.org/fred",
        api_key=os.environ["FRED_API_KEY"],
        api_key_param="api_key",
    )
```

```python
# services/mcp-server/src/tools/fred_tools.py
from mcp.server.fastmcp import FastMCP
from ..clients.fred_client import fred_client

_SERIES_TOOLS = {
    "fred_federal_funds_rate": ("DFF", "Effective federal funds rate, daily."),
    "fred_10y_treasury_yield": ("DGS10", "10-year Treasury constant maturity yield, daily."),
    "fred_2y_treasury_yield": ("DGS2", "2-year Treasury constant maturity yield, daily."),
    "fred_cpi": ("CPIAUCSL", "Consumer Price Index for All Urban Consumers, monthly."),
    "fred_unemployment_rate": ("UNRATE", "US unemployment rate, monthly."),
    "fred_nonfarm_payrolls": ("PAYEMS", "Total nonfarm payroll employment, monthly."),
    "fred_real_gdp": ("GDPC1", "Real Gross Domestic Product, quarterly."),
    "fred_vix": ("VIXCLS", "CBOE Volatility Index, daily."),
    "fred_consumer_sentiment": ("UMCSENT", "University of Michigan Consumer Sentiment Index, monthly."),
}

def register_fred_tools(app: FastMCP) -> None:
    client = fred_client()

    def make_series_tool(series_id: str):
        async def tool(observation_start: str | None = None, observation_end: str | None = None) -> dict:
            params = {"series_id": series_id, "file_type": "json"}
            if observation_start:
                params["observation_start"] = observation_start
            if observation_end:
                params["observation_end"] = observation_end
            return await client.get("/series/observations", params)
        return tool

    for tool_name, (series_id, description) in _SERIES_TOOLS.items():
        fn = make_series_tool(series_id)
        fn.__name__ = tool_name
        fn.__doc__ = description
        app.add_tool(fn, name=tool_name, description=description)

    @app.tool()
    async def fred_series_search(search_text: str) -> dict:
        """Search FRED for series matching free-text terms (e.g. 'unemployment')."""
        return await client.get("/series/search", {"search_text": search_text, "file_type": "json"})

    @app.tool()
    async def fred_release_calendar(realtime_start: str, realtime_end: str) -> dict:
        """Upcoming FRED data release dates within a date range (YYYY-MM-DD)."""
        return await client.get("/releases/dates", {
            "realtime_start": realtime_start, "realtime_end": realtime_end, "file_type": "json",
        })
```

Note: `_SERIES_TOOLS` is a data table driving `app.add_tool`, FastMCP's imperative registration API — used here (instead of nine near-identical `@app.tool()` blocks) because the nine series tools are genuinely parameter-identical, differing only in which fixed series ID they query.

- [ ] **Step 4: Run to verify pass**

Run: `cd services/mcp-server && pytest tests/unit/test_fred_tools.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add services/mcp-server/src/clients/fred_client.py services/mcp-server/src/tools/fred_tools.py services/mcp-server/tests/unit/test_fred_tools.py
git commit -m "feat: add FRED MCP tools (11)"
```

### Task 11: Marketaux tool (1)

**Files:**
- Create: `services/mcp-server/src/clients/marketaux_client.py`
- Create: `services/mcp-server/src/tools/marketaux_tools.py`
- Test: `services/mcp-server/tests/unit/test_marketaux_tools.py`

**Interfaces:**
- Produces: `register_marketaux_tools(app: FastMCP) -> None`, registering `marketaux_news_all`. Response items must include an `"uuid"` field per article — the Input Data Agent's news-diff gate (Task 20) depends on it.

- [ ] **Step 1: Write the failing test**

```python
# services/mcp-server/tests/unit/test_marketaux_tools.py
import pytest
import respx
import httpx
from src.clients.marketaux_client import marketaux_client

@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("MARKETAUX_API_KEY", "test-key")

@pytest.mark.asyncio
@respx.mock
async def test_news_all_returns_articles_with_uuid():
    respx.get("https://api.marketaux.com/v1/news/all").mock(
        return_value=httpx.Response(200, json={"data": [{"uuid": "abc-123", "title": "Test"}]})
    )
    client = marketaux_client()
    result = await client.get("/news/all", {"symbols": "AAPL"})
    assert result["data"][0]["uuid"] == "abc-123"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/mcp-server && pytest tests/unit/test_marketaux_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/mcp-server/src/clients/marketaux_client.py
import os
from .base import ProviderClient

def marketaux_client() -> ProviderClient:
    return ProviderClient(
        base_url="https://api.marketaux.com/v1",
        api_key=os.environ["MARKETAUX_API_KEY"],
        api_key_param="api_token",
    )
```

```python
# services/mcp-server/src/tools/marketaux_tools.py
from mcp.server.fastmcp import FastMCP
from ..clients.marketaux_client import marketaux_client

def register_marketaux_tools(app: FastMCP) -> None:
    client = marketaux_client()

    @app.tool()
    async def marketaux_news_all(symbols: str) -> dict:
        """Latest news articles (per-article sentiment, entity-tagged) for comma-separated stock symbols."""
        return await client.get("/news/all", {"symbols": symbols})
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/mcp-server && pytest tests/unit/test_marketaux_tools.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add services/mcp-server/src/clients/marketaux_client.py services/mcp-server/src/tools/marketaux_tools.py services/mcp-server/tests/unit/test_marketaux_tools.py
git commit -m "feat: add Marketaux MCP tool"
```

### Task 12: Custom tools — manager scoring formula and process-history query

The two provider-independent tools from spec §3. The scoring tool wraps Task 3's pure function so the Manager agent's arithmetic step is traceable through the MCP tool-call log; the process-history tool wraps Task 6's `query_process_history`.

**Files:**
- Create: `services/mcp-server/src/tools/scoring_tool.py`
- Create: `services/mcp-server/src/tools/process_history_tool.py`
- Test: `services/mcp-server/tests/unit/test_scoring_tool.py`
- Test: `services/mcp-server/tests/unit/test_process_history_tool.py`

**Interfaces:**
- Consumes: `compute_verdict` (Task 3), `query_process_history` (Task 6)
- Produces: `register_scoring_tool(app: FastMCP) -> None` registering `score_verdict(bull_claims: list[dict], bear_claims: list[dict], risk_level: str) -> dict`; `register_process_history_tool(app: FastMCP) -> None` registering `query_process_history_tool(symbol: str, since: str | None = None) -> list[dict]`. Task 21 (Manager agent node) and Task 30 (Chat) call these tool names respectively via MCP.

- [ ] **Step 1: Write the failing test for the scoring tool**

```python
# services/mcp-server/tests/unit/test_scoring_tool.py
import pytest
from mcp.server.fastmcp import FastMCP
from src.tools.scoring_tool import register_scoring_tool

@pytest.mark.asyncio
async def test_score_verdict_tool_delegates_to_compute_verdict():
    app = FastMCP("test")
    register_scoring_tool(app)
    tools = await app.list_tools()
    assert any(t.name == "score_verdict" for t in tools)

    result = await app.call_tool("score_verdict", {
        "bull_claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other"}],
        "bear_claims": [],
        "risk_level": "low",
    })
    payload = result[0] if isinstance(result, tuple) else result
    assert payload  # non-empty verdict returned
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/mcp-server && pytest tests/unit/test_scoring_tool.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/mcp-server/src/tools/scoring_tool.py
from mcp.server.fastmcp import FastMCP
from .scoring import compute_verdict

def register_scoring_tool(app: FastMCP) -> None:
    @app.tool()
    async def score_verdict(bull_claims: list[dict], bear_claims: list[dict], risk_level: str) -> dict:
        """Compute the deterministic bull/bear/risk verdict (net score, confidence, label) from structured claims."""
        return compute_verdict(bull_claims, bear_claims, risk_level)  # type: ignore[arg-type]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/mcp-server && pytest tests/unit/test_scoring_tool.py -v`
Expected: 1 passed

- [ ] **Step 5: Write the failing test for the process-history tool**

```python
# services/mcp-server/tests/unit/test_process_history_tool.py
import pytest
import boto3
from moto import mock_aws
from mcp.server.fastmcp import FastMCP
from datetime import datetime, timezone
from src.tools.process_history_tool import register_process_history_tool
from common.dynamo import append_process_history, ensure_tables_for_test

@pytest.mark.asyncio
async def test_process_history_tool_returns_entries_for_symbol():
    with mock_aws():
        ensure_tables_for_test()
        append_process_history("AAPL", "Sentiment", reason="news_cascade", status="finished",
                                timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
        app = FastMCP("test")
        register_process_history_tool(app)
        result = await app.call_tool("query_process_history_tool", {"symbol": "AAPL"})
        assert result  # non-empty
```

- [ ] **Step 6: Run to verify failure**

Run: `cd services/mcp-server && pytest tests/unit/test_process_history_tool.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 7: Implement**

```python
# services/mcp-server/src/tools/process_history_tool.py
from mcp.server.fastmcp import FastMCP
from datetime import datetime
from common.dynamo import query_process_history

def register_process_history_tool(app: FastMCP) -> None:
    @app.tool()
    async def query_process_history_tool(symbol: str, since: str | None = None) -> list[dict]:
        """Query the append-only process-history log for a symbol: every agent run, why it ran, and its status."""
        since_dt = datetime.fromisoformat(since) if since else None
        return query_process_history(symbol, since=since_dt)
```

- [ ] **Step 8: Run to verify pass**

Run: `cd services/mcp-server && pytest tests/unit/test_process_history_tool.py -v`
Expected: 1 passed

- [ ] **Step 9: Verify the full server now assembles**

Run: `cd services/mcp-server && python -c "from src.server import create_app; create_app()"`
Expected: no error — all six `register_*` modules now exist and import cleanly

- [ ] **Step 10: Commit**

```bash
git add services/mcp-server/src/tools/scoring_tool.py services/mcp-server/src/tools/process_history_tool.py services/mcp-server/tests/unit/test_scoring_tool.py services/mcp-server/tests/unit/test_process_history_tool.py
git commit -m "feat: add manager-scoring-formula and process-history-query MCP tools"
```

### Task 13: MCP server Dockerfile and real-transport integration test

Satisfies spec §11's integration-test requirement: all 35 tools discoverable and callable through the real MCP protocol, not mocked at the transport layer.

**Files:**
- Create: `services/mcp-server/Dockerfile`
- Test: `services/mcp-server/tests/integration/test_mcp_transport.py`

**Interfaces:**
- Consumes: `create_app` (Task 7)

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# services/mcp-server/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY packages/common /packages/common
COPY services/mcp-server/pyproject.toml services/mcp-server/pyproject.toml
COPY services/mcp-server/src services/mcp-server/src
WORKDIR /app/services/mcp-server
RUN pip install --no-cache-dir .
EXPOSE 8001
CMD ["python", "-m", "src.server"]
```

- [ ] **Step 2: Write the failing integration test (real MCP client/server over in-memory transport)**

```python
# services/mcp-server/tests/integration/test_mcp_transport.py
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session
from src.server import create_app

EXPECTED_TOOL_COUNT = 35

@pytest.mark.asyncio
async def test_all_35_tools_are_discoverable_over_real_transport(monkeypatch):
    for var in ["FINNHUB_API_KEY", "FMP_API_KEY", "FRED_API_KEY", "MARKETAUX_API_KEY"]:
        monkeypatch.setenv(var, "test-key")
    app = create_app()
    async with create_connected_server_and_client_session(app._mcp_server) as client:
        tools = await client.list_tools()
        assert len(tools.tools) == EXPECTED_TOOL_COUNT

@pytest.mark.asyncio
async def test_quote_tool_is_callable_over_real_transport(monkeypatch, respx_mock):
    import httpx
    for var in ["FINNHUB_API_KEY", "FMP_API_KEY", "FRED_API_KEY", "MARKETAUX_API_KEY"]:
        monkeypatch.setenv(var, "test-key")
    respx_mock.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 150.0})
    )
    app = create_app()
    async with create_connected_server_and_client_session(app._mcp_server) as client:
        result = await client.call_tool("finnhub_quote", {"symbol": "AAPL"})
        assert not result.isError
```

- [ ] **Step 3: Run to verify failure**

Run: `cd services/mcp-server && pytest tests/integration/test_mcp_transport.py -v`
Expected: FAIL initially on missing fixtures/imports — add `pytest-respx` fixture support and confirm `mcp.shared.memory.create_connected_server_and_client_session` matches the installed `mcp` SDK version's actual test-harness API (consult the SDK's own test suite for the current helper name if this import path has changed).

- [ ] **Step 4: Fix imports/implementation until both tests pass**

Run: `cd services/mcp-server && pytest tests/integration/test_mcp_transport.py -v`
Expected: 2 passed

- [ ] **Step 5: Build the Docker image and smoke-test it**

Run: `docker build -f services/mcp-server/Dockerfile -t mcp-server:local .`
Expected: image builds successfully

- [ ] **Step 6: Commit**

```bash
git add services/mcp-server/Dockerfile services/mcp-server/tests/integration/test_mcp_transport.py
git commit -m "test: add real-transport MCP integration test and server Dockerfile"
```

---

## Phase E — Scheduler: MCP Client Wiring and the Input Data Agent

The Scheduler is the only service that calls live tools (spec §2.2). It's an MCP client of all three servers: the self-built one (all 35 tools), and the two third-party ones (TradingView MCP, Stock Scanner MCP), connected via `langchain-mcp-adapters`' `MultiServerMCPClient`.

### Task 14: MultiServerMCPClient wiring to all three MCP servers

**Files:**
- Create: `services/scheduler/src/mcp_clients.py`
- Test: `services/scheduler/tests/unit/test_mcp_clients.py`

**Interfaces:**
- Produces: `build_mcp_client() -> MultiServerMCPClient` configured with three server entries keyed `"own"`, `"tradingview"`, `"stock_scanner"`; `async def call_tool(client: MultiServerMCPClient, server: str, tool_name: str, **kwargs) -> dict`. Task 16 (Input Data Agent) and Task 21 (Manager agent) use `call_tool` exclusively rather than touching `MultiServerMCPClient` directly, so the circuit breaker (Task 5) can be applied uniformly for the `"tradingview"` and `"stock_scanner"` servers.

- [ ] **Step 1: Write the failing test**

```python
# services/scheduler/tests/unit/test_mcp_clients.py
import os
from src.mcp_clients import build_mcp_client

def test_client_configures_all_three_servers(monkeypatch):
    monkeypatch.setenv("OWN_MCP_SERVER_URL", "http://mcp-server:8001/mcp")
    monkeypatch.setenv("TRADINGVIEW_MCP_URL", "http://tradingview-mcp:9001/mcp")
    monkeypatch.setenv("STOCK_SCANNER_MCP_URL", "http://stock-scanner-mcp:9002/mcp")
    client = build_mcp_client()
    assert set(client.connections.keys()) == {"own", "tradingview", "stock_scanner"}
    assert client.connections["own"]["url"] == "http://mcp-server:8001/mcp"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_mcp_clients.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/mcp_clients.py
import os
from datetime import datetime, timezone
from langchain_mcp_adapters.client import MultiServerMCPClient
from .rate_limit.circuit_breaker import CircuitBreaker

CIRCUIT_BREAKER_PROTECTED_SERVERS = {"tradingview", "stock_scanner"}

def build_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient({
        "own": {"url": os.environ["OWN_MCP_SERVER_URL"], "transport": "streamable_http"},
        "tradingview": {"url": os.environ["TRADINGVIEW_MCP_URL"], "transport": "streamable_http"},
        "stock_scanner": {"url": os.environ["STOCK_SCANNER_MCP_URL"], "transport": "streamable_http"},
    })

# Both third-party servers share ONE breaker instance (spec §7 — they depend on the same
# upstream TradingView infrastructure), so this lives at module scope, not per-server.
_tradingview_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=300)

class CircuitOpenError(Exception):
    pass

async def call_tool(client: MultiServerMCPClient, server: str, tool_name: str, **kwargs) -> dict:
    now = datetime.now(timezone.utc)
    protected = server in CIRCUIT_BREAKER_PROTECTED_SERVERS
    if protected and not _tradingview_breaker.allow_call(now):
        raise CircuitOpenError(f"circuit open for shared TradingView dependency (server={server})")
    tools = await client.get_tools(server_name=server)
    tool = next(t for t in tools if t.name == tool_name)
    try:
        result = await tool.ainvoke(kwargs)
    except Exception:
        if protected:
            _tradingview_breaker.record_failure(now)
        raise
    if protected:
        _tradingview_breaker.record_success(now)
    return result
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_mcp_clients.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add services/scheduler/src/mcp_clients.py services/scheduler/tests/unit/test_mcp_clients.py
git commit -m "feat: wire MultiServerMCPClient to all three MCP servers with shared circuit breaker"
```

### Task 15: Market-hours helper and per-provider schedule config

Encodes spec §7's table as data + a market-hours predicate, including the corrected discovery-tier cadence (30 min, active 4:00am–8:00pm ET, paused 8:00pm–4:00am ET).

**Files:**
- Create: `services/scheduler/src/schedule_config.py`
- Test: `services/scheduler/tests/unit/test_schedule_config.py`

**Interfaces:**
- Produces: `is_regular_market_hours(now_et: datetime) -> bool`, `is_extended_hours(now_et: datetime) -> bool` (4:00am–8:00pm ET), `ProviderSchedule` (dataclass: `cadence_seconds_regular: int`, `cadence_seconds_extended: int | None`, `active_overnight: bool`), `SCHEDULES: dict[str, ProviderSchedule]` keyed `"marketaux"`, `"fmp"`, `"finnhub_static"`, `"finnhub_live"`, `"fred_slow"`, `"fred_vix"`, `"technical_options"`, `"discovery"`. Task 24's async scheduler loop drives its cadence entirely from this module.

- [ ] **Step 1: Write the failing tests**

```python
# services/scheduler/tests/unit/test_schedule_config.py
from datetime import datetime
from zoneinfo import ZoneInfo
from src.schedule_config import is_regular_market_hours, is_extended_hours, SCHEDULES

ET = ZoneInfo("America/New_York")

def test_regular_market_hours_930_to_400pm():
    assert is_regular_market_hours(datetime(2026, 1, 5, 10, 0, tzinfo=ET)) is True  # Monday
    assert is_regular_market_hours(datetime(2026, 1, 5, 9, 0, tzinfo=ET)) is False
    assert is_regular_market_hours(datetime(2026, 1, 5, 16, 30, tzinfo=ET)) is False

def test_regular_market_hours_excludes_weekends():
    assert is_regular_market_hours(datetime(2026, 1, 3, 10, 0, tzinfo=ET)) is False  # Saturday

def test_extended_hours_4am_to_8pm():
    assert is_extended_hours(datetime(2026, 1, 5, 5, 0, tzinfo=ET)) is True
    assert is_extended_hours(datetime(2026, 1, 5, 19, 59, tzinfo=ET)) is True
    assert is_extended_hours(datetime(2026, 1, 5, 3, 0, tzinfo=ET)) is False
    assert is_extended_hours(datetime(2026, 1, 5, 20, 1, tzinfo=ET)) is False

def test_discovery_schedule_matches_marketaux_regular_hours_cadence():
    assert SCHEDULES["discovery"].cadence_seconds_regular == SCHEDULES["marketaux"].cadence_seconds_regular == 1800
    assert SCHEDULES["discovery"].active_overnight is False

def test_marketaux_extended_hours_cadence_is_90_minutes():
    assert SCHEDULES["marketaux"].cadence_seconds_extended == 5400
    assert SCHEDULES["marketaux"].active_overnight is False

def test_discovery_has_no_separate_extended_tier_reuses_regular_cadence_throughout():
    # Per spec §7: discovery uses ONE flat 30-min cadence across the whole 4am-8pm window,
    # not Marketaux's separate 90-min pre/after-hours tier.
    assert SCHEDULES["discovery"].cadence_seconds_extended == SCHEDULES["discovery"].cadence_seconds_regular

def test_technical_options_schedule_matches_discovery_tier_precedent_not_finnhub_live():
    # TradingView-backed per-symbol technicals/options depend on the same circuit-breaker-
    # protected TradingView scanner infrastructure as the discovery tier (spec §7) — the risk
    # is total daily call volume against that one fragile shared dependency, not burst rate
    # (the sliding-window limiter already caps bursts regardless of which tier a tool is on).
    # 7 tools x 30 symbols at 5-min cadence is 40,000+ calls/day; at 30-min it's ~10,000/day,
    # matching the same reasoning and number already established for the discovery tier and
    # Marketaux's regular-hours cadence — reused here rather than introducing a new one.
    assert SCHEDULES["technical_options"].cadence_seconds_regular == SCHEDULES["discovery"].cadence_seconds_regular == 1800
    assert SCHEDULES["technical_options"].cadence_seconds_regular != SCHEDULES["finnhub_live"].cadence_seconds_regular
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_schedule_config.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/schedule_config.py
from dataclasses import dataclass
from datetime import datetime, time

_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)
_EXTENDED_OPEN = time(4, 0)
_EXTENDED_CLOSE = time(20, 0)

def is_regular_market_hours(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    return _REGULAR_OPEN <= now_et.time() < _REGULAR_CLOSE

def is_extended_hours(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    return _EXTENDED_OPEN <= now_et.time() < _EXTENDED_CLOSE

@dataclass(frozen=True)
class ProviderSchedule:
    cadence_seconds_regular: int
    cadence_seconds_extended: int | None  # None => not polled outside regular hours
    active_overnight: bool

SCHEDULES: dict[str, ProviderSchedule] = {
    "marketaux": ProviderSchedule(cadence_seconds_regular=1800, cadence_seconds_extended=5400, active_overnight=False),
    "fmp": ProviderSchedule(cadence_seconds_regular=86400, cadence_seconds_extended=None, active_overnight=False),
    "finnhub_static": ProviderSchedule(cadence_seconds_regular=86400, cadence_seconds_extended=None, active_overnight=False),
    "finnhub_live": ProviderSchedule(cadence_seconds_regular=60, cadence_seconds_extended=60, active_overnight=False),
    "fred_slow": ProviderSchedule(cadence_seconds_regular=86400, cadence_seconds_extended=None, active_overnight=False),
    "fred_vix": ProviderSchedule(cadence_seconds_regular=3600, cadence_seconds_extended=None, active_overnight=False),
    # TradingView-backed per-symbol technicals/options (Full Technical Analysis, Options
    # Chain, etc., Task 16): a different provider from Finnhub, with no per-minute quota of
    # its own but the same circuit-breaker-protected, fragile shared upstream as the discovery
    # tier below (Task 5) — the risk here is total daily call volume against that one
    # dependency, not burst rate (the sliding-window limiter already caps bursts independent
    # of schedule tier). No stated reason per-symbol technicals need fresher data than
    # discovery's market-wide context does, so this reuses the same 30-min number already
    # established for the discovery tier and Marketaux's regular-hours cadence, rather than
    # introducing a new one.
    "technical_options": ProviderSchedule(cadence_seconds_regular=1800, cadence_seconds_extended=None, active_overnight=False),
    # Discovery tier: flat 30-min cadence across the whole 4am-8pm extended window, reusing
    # Marketaux's regular-hours number per spec §7 rather than introducing a separate tier.
    "discovery": ProviderSchedule(cadence_seconds_regular=1800, cadence_seconds_extended=1800, active_overnight=False),
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_schedule_config.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add services/scheduler/src/schedule_config.py services/scheduler/tests/unit/test_schedule_config.py
git commit -m "feat: encode per-provider schedule config incl. corrected discovery-tier cadence"
```

### Task 16: Input Data Agent — fetch plan, change detection, and per-symbol orchestration

Spec §4.1 describes the news-diff gate specifically for Marketaux. The UI spec (§8.1) shows a Fundamentals node staying "an hour old" while Sentiment updates "2 minutes ago" — which only makes sense if **every** specialist's underlying data can independently trigger its own re-run when it changes, with news simply being the most frequent case. This task implements that generalized change-detection gate: any tool's freshly-fetched value is diffed against its previous cached value (UUID-set diff for Marketaway news, deep-equality diff for everything else); a specialist's group only re-runs when at least one of its underlying tools actually changed.

**Files:**
- Create: `services/scheduler/src/input_data_agent.py`
- Test: `services/scheduler/tests/unit/test_input_data_agent.py`

**Interfaces:**
- Consumes: `call_tool` (Task 14), `SCHEDULES`, `is_regular_market_hours`, `is_extended_hours` (Task 15), `read_tool_result`, `write_tool_result`, `append_process_history` (Task 6)
- Consumes: `SlidingWindowLimiter`, `DailyCapScheduler` (Task 4)
- Produces: `FetchSpec` (dataclass), `FETCH_PLAN: list[FetchSpec]`, `fmp_is_due_today(symbol: str, watchlist: list[str], today: date) -> bool`, `diff_changed(previous: dict | None, current: dict, is_news: bool) -> bool`, `InputDataAgentResult` (dataclass: `changed_specialists: set[str]`, `is_new_symbol: bool`), `async def run_input_data_agent_for_symbol(mcp_client, symbol: str, watchlist: list[str], is_new_symbol: bool, now_utc: datetime, now_et: datetime) -> InputDataAgentResult`, `async def cross_check_analyst_price_targets(mcp_client, symbol: str) -> dict`. Task 24's `scheduler_tick` calls `run_input_data_agent_for_symbol` once per watchlist symbol per tick and uses `changed_specialists` to decide which specialist nodes the graph should execute vs. skip.

- [ ] **Step 1: Write the failing tests for change detection and rotation**

```python
# services/scheduler/tests/unit/test_input_data_agent.py
from datetime import date
from src.input_data_agent import diff_changed, fmp_is_due_today, FETCH_PLAN

def test_diff_changed_news_uses_uuid_set():
    previous = {"data": [{"uuid": "a"}, {"uuid": "b"}]}
    same = {"data": [{"uuid": "b"}, {"uuid": "a"}]}  # same set, different order
    changed = {"data": [{"uuid": "a"}, {"uuid": "c"}]}
    assert diff_changed(previous, same, is_news=True) is False
    assert diff_changed(previous, changed, is_news=True) is True

def test_diff_changed_non_news_uses_deep_equality():
    assert diff_changed({"price": 150}, {"price": 150}, is_news=False) is False
    assert diff_changed({"price": 150}, {"price": 151}, is_news=False) is True

def test_diff_changed_first_fetch_always_counts_as_changed():
    assert diff_changed(None, {"price": 150}, is_news=False) is True

def test_fmp_rotation_covers_watchlist_over_3_days_evenly():
    watchlist = [f"SYM{i}" for i in range(30)]
    day0 = date(2026, 1, 1)  # toordinal() % 3 == some value; test all 3 consecutive days
    due_counts = []
    for offset in range(3):
        day = date.fromordinal(day0.toordinal() + offset)
        due_counts.append(sum(1 for s in watchlist if fmp_is_due_today(s, watchlist, day)))
    assert due_counts == [10, 10, 10]

def test_fmp_rotation_is_stable_for_a_given_symbol_and_day():
    watchlist = ["AAPL", "MSFT", "GOOG"]
    day = date(2026, 3, 15)
    assert fmp_is_due_today("AAPL", watchlist, day) == fmp_is_due_today("AAPL", watchlist, day)

def test_fetch_plan_covers_all_33_self_built_tools_plus_technical_and_options_extras():
    own_server_tools = {f.tool_name for f in FETCH_PLAN if f.server == "own"}
    # 33 total self-built tools minus the 2 ad hoc FRED utility tools (search/release calendar),
    # which are not part of scheduled fetching (spec doesn't require them on a cadence).
    assert len(own_server_tools) == 31
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_input_data_agent.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `diff_changed`, `fmp_is_due_today`, and `FETCH_PLAN`**

```python
# services/scheduler/src/input_data_agent.py
from dataclasses import dataclass, field
from datetime import date, datetime

def diff_changed(previous: dict | None, current: dict, is_news: bool) -> bool:
    if previous is None:
        return True
    if is_news:
        prev_uuids = {a["uuid"] for a in previous.get("data", [])}
        curr_uuids = {a["uuid"] for a in current.get("data", [])}
        return prev_uuids != curr_uuids
    return previous != current

_FMP_ROTATION_DAYS = 3

def fmp_is_due_today(symbol: str, watchlist: list[str], today: date) -> bool:
    group = watchlist.index(symbol) % _FMP_ROTATION_DAYS
    return group == today.toordinal() % _FMP_ROTATION_DAYS

@dataclass(frozen=True)
class FetchSpec:
    tool_name: str
    server: str  # "own" | "tradingview" | "stock_scanner"
    specialist: str  # "fundamentals" | "technical" | "sentiment" | "macro_options"
    schedule_key: str
    per_symbol: bool
    is_news: bool = False

FETCH_PLAN: list[FetchSpec] = [
    # Fundamentals — Finnhub static (9)
    FetchSpec("finnhub_company_profile", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_peers", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_basic_financials", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_earnings_calendar", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_earnings_surprises", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_insider_transactions", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_insider_sentiment", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_lobbying_data", "own", "fundamentals", "finnhub_static", True),
    FetchSpec("finnhub_usa_spending", "own", "fundamentals", "finnhub_static", True),
    # Fundamentals — FMP per-symbol (7, on the 3-day rotation) + global calendars (2)
    FetchSpec("fmp_income_statement", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_balance_sheet_statement", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_cash_flow_statement", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_financial_ratios", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_key_metrics", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_dcf_valuation", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_ratings_snapshot", "own", "fundamentals", "fmp", True),
    FetchSpec("fmp_dividends_calendar", "own", "fundamentals", "fmp", False),
    FetchSpec("fmp_stock_splits_calendar", "own", "fundamentals", "fmp", False),
    # Sentiment — Marketaux (news-diff by UUID) + Finnhub company news
    FetchSpec("marketaux_news_all", "own", "sentiment", "marketaux", True, is_news=True),
    FetchSpec("finnhub_company_news", "own", "sentiment", "finnhub_live", True, is_news=True),
    # Technical — Finnhub quote uses finnhub_live (its own per-minute quota, sliding-window
    # limited). TradingView-backed per-symbol technicals are a DIFFERENT provider with no
    # per-minute quota of its own but the same circuit-breaker-protected shared upstream as
    # the discovery tier (spec §7) — they get their own "technical_options" cadence tier
    # (Task 15, 30 min, matching the discovery-tier/Marketaux precedent), not finnhub_live's,
    # since the risk against that shared dependency is total daily call volume, not burst
    # rate. Still protected by the shared circuit breaker since server != "own".
    FetchSpec("finnhub_quote", "own", "technical", "finnhub_live", True),
    FetchSpec("full_technical_analysis", "tradingview", "technical", "technical_options", True),
    FetchSpec("multi_timeframe_analysis", "tradingview", "technical", "technical_options", True),
    FetchSpec("volume_confirmation_analysis", "tradingview", "technical", "technical_options", True),
    FetchSpec("candlestick_pattern_analysis", "tradingview", "technical", "technical_options", True),
    FetchSpec("tradingview_technicals", "stock_scanner", "technical", "technical_options", True),
    # Macro/Options — FRED series (global, not per-symbol) + TradingView options (per-symbol,
    # same 30-min technical_options cadence tier as the technicals above, for the same reason)
    FetchSpec("fred_federal_funds_rate", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_10y_treasury_yield", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_2y_treasury_yield", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_cpi", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_unemployment_rate", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_nonfarm_payrolls", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_real_gdp", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_consumer_sentiment", "own", "macro_options", "fred_slow", False),
    FetchSpec("fred_vix", "own", "macro_options", "fred_vix", False),
    FetchSpec("fmp_economic_indicators", "own", "macro_options", "fmp", False),
    FetchSpec("options_chain", "tradingview", "macro_options", "technical_options", True),
    FetchSpec("unusual_options_activity", "tradingview", "macro_options", "technical_options", True),
]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_input_data_agent.py -v`
Expected: 5 passed

- [ ] **Step 5: Write the failing tests for per-symbol orchestration**

```python
# append to services/scheduler/tests/unit/test_input_data_agent.py
import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from zoneinfo import ZoneInfo
from src.input_data_agent import run_input_data_agent_for_symbol

ET = ZoneInfo("America/New_York")

@pytest.mark.asyncio
async def test_new_symbol_triggers_full_fetch_and_all_specialists_marked_changed(monkeypatch):
    monkeypatch.setattr("src.input_data_agent.call_tool", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr("src.input_data_agent.read_tool_result", lambda pk: None)
    monkeypatch.setattr("src.input_data_agent.write_tool_result", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.record_fetch_attempt", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.get_last_fetch_attempt", lambda pk: None)

    result = await run_input_data_agent_for_symbol(
        mcp_client=object(), symbol="AAPL", watchlist=["AAPL"], is_new_symbol=True,
        now_utc=datetime(2026, 1, 5, 15, 0), now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET),
    )
    assert result.is_new_symbol is True
    assert result.changed_specialists == {"fundamentals", "technical", "sentiment", "macro_options"}

@pytest.mark.asyncio
async def test_scheduled_tick_only_marks_specialists_whose_data_actually_changed(monkeypatch):
    async def fake_call_tool(client, server, tool_name, **kwargs):
        if tool_name == "marketaux_news_all":
            return {"data": [{"uuid": "new-1"}]}
        return {"unchanged": True}

    def fake_read(pk):
        if "marketaux_news_all" in pk:
            return {"data": [{"uuid": "old-1"}]}
        return {"unchanged": True}

    monkeypatch.setattr("src.input_data_agent.call_tool", fake_call_tool)
    monkeypatch.setattr("src.input_data_agent.read_tool_result", fake_read)
    monkeypatch.setattr("src.input_data_agent.write_tool_result", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.record_fetch_attempt", lambda *a, **k: None)
    # No prior attempt recorded for anything -> every schedule-driven tool is due this tick,
    # isolating the assertion to diff_changed's behavior rather than cadence gating.
    monkeypatch.setattr("src.input_data_agent.get_last_fetch_attempt", lambda pk: None)

    result = await run_input_data_agent_for_symbol(
        mcp_client=object(), symbol="AAPL", watchlist=["AAPL"], is_new_symbol=False,
        now_utc=datetime(2026, 1, 5, 15, 0), now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET),
    )
    assert result.changed_specialists == {"sentiment"}
```

- [ ] **Step 6: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_input_data_agent.py -v`
Expected: FAIL — `run_input_data_agent_for_symbol` not defined

- [ ] **Step 7: Implement orchestration**

```python
# append to services/scheduler/src/input_data_agent.py
import logging
from .mcp_clients import call_tool
from common.dynamo import (
    read_tool_result, write_tool_result, append_process_history,
    record_fetch_attempt, get_last_fetch_attempt,
)
from .schedule_config import SCHEDULES, is_regular_market_hours, is_extended_hours
from .rate_limit.sliding_window import SlidingWindowLimiter
from .rate_limit.daily_cap import DailyCapScheduler

logger = logging.getLogger(__name__)

_TTL_SECONDS = {
    "marketaux": 1800, "fmp": 3 * 86400, "finnhub_static": 86400,
    "finnhub_live": 60, "fred_slow": 86400, "fred_vix": 3600, "technical_options": 1800,
}

@dataclass
class InputDataAgentResult:
    changed_specialists: set[str] = field(default_factory=set)
    is_new_symbol: bool = False

# Finnhub's real constraint is per-minute (60 calls/min free tier), not daily, so it's
# protected by a sliding window rather than a budget (spec §7). Marketaux's cadence/batching
# keeps it comfortably under its daily cap; this daily cap is the "protective safety cap as a
# backstop" spec §7 calls for on top of that, shared across the whole watchlist.
_finnhub_live_limiter = SlidingWindowLimiter(max_calls=55, window_seconds=60)
_marketaux_daily_backstop = DailyCapScheduler(daily_cap=100, safety_margin=10)

def _is_due(spec: FetchSpec, pk: str, now_utc: datetime, now_et: datetime, is_new_symbol: bool) -> bool:
    if is_new_symbol:
        return True
    schedule = SCHEDULES[spec.schedule_key]
    if not schedule.active_overnight and not is_extended_hours(now_et):
        return False

    if spec.schedule_key == "finnhub_live":
        return _finnhub_live_limiter.allow(now_utc)  # per-minute budget; false = skip this tick
    if spec.schedule_key == "marketaux":
        return _marketaux_daily_backstop.allow(now_utc)  # daily backstop; false = skip until UTC midnight

    # Every other schedule-driven tool (fmp, finnhub_static, fred_slow, fred_vix,
    # technical_options) has no dedicated rate limiter of its own, so cadence is enforced
    # directly here: has enough time actually elapsed since the last successful fetch attempt?
    # (This was the bug: previously this function only checked "is it market/extended hours",
    # which is True on every one of the Scheduler's 60s ticks — meaning finnhub_static's 11
    # daily tools, for example, would have been called once per minute per symbol instead of
    # once per day, directly contradicting spec §7's per-provider cadences.)
    last_attempt = get_last_fetch_attempt(pk)
    if last_attempt is None:
        return True
    if schedule.cadence_seconds_extended is not None and is_extended_hours(now_et) and not is_regular_market_hours(now_et):
        cadence = schedule.cadence_seconds_extended
    else:
        cadence = schedule.cadence_seconds_regular
    return (now_utc - last_attempt).total_seconds() >= cadence

async def run_input_data_agent_for_symbol(
    mcp_client, symbol: str, watchlist: list[str], is_new_symbol: bool,
    now_utc: datetime, now_et: datetime,
) -> InputDataAgentResult:
    result = InputDataAgentResult(is_new_symbol=is_new_symbol)

    for spec in FETCH_PLAN:
        pk = f"{symbol}#{spec.tool_name}" if spec.per_symbol else f"GLOBAL#{spec.tool_name}"

        if spec.per_symbol and spec.schedule_key == "fmp" and not is_new_symbol:
            # fmp_is_due_today's 3-day rotation already spaces a given symbol's FMP calls
            # ~3 days apart, comfortably wider than fmp's own 1-day generic cadence below — so
            # the two checks are complementary (rotation picks the day, cadence is a no-op
            # backstop on that day), not in conflict or bypassing one another.
            if not fmp_is_due_today(symbol, watchlist, now_utc.date()):
                continue
        if not _is_due(spec, pk, now_utc, now_et, is_new_symbol):
            continue

        params = {"symbol": symbol} if spec.per_symbol else {}
        try:
            current = await call_tool(mcp_client, spec.server, spec.tool_name, **params)
        except Exception:
            # One tool failing (e.g. Marketaux unreachable) must never block the rest of this
            # symbol's scheduled fetches (spec §10) — skip it, retry on the next tick. Deliberately
            # do NOT record a fetch attempt here: a failed call shouldn't push the next retry a
            # full cadence period out, only a successful one should reset that clock.
            logger.warning("fetch failed for %s/%s, will retry next tick", symbol, spec.tool_name, exc_info=True)
            continue

        record_fetch_attempt(pk, now_utc)
        previous = read_tool_result(pk)

        if diff_changed(previous, current, is_news=spec.is_news):
            write_tool_result(pk, current, ttl_seconds=_TTL_SECONDS[spec.schedule_key])
            result.changed_specialists.add(spec.specialist)
            append_process_history(
                symbol, spec.specialist,
                reason="new_symbol" if is_new_symbol else ("news_cascade" if spec.is_news else "scheduled_refresh"),
                status="finished", timestamp=now_utc,
            )

    return result

async def cross_check_analyst_price_targets(mcp_client, symbol: str) -> dict:
    """Cross-checks FMP's ratings/price-target data against TradingView's technical-analysis
    pivot-based target levels, since a single source can carry an outlier estimate. Field
    names on both sides should be confirmed against each provider's live response schema
    during implementation — this wires the two calls and the comparison, not the exact keys."""
    fmp_result = await call_tool(mcp_client, "own", "fmp_ratings_snapshot", symbol=symbol)
    tv_result = await call_tool(mcp_client, "tradingview", "full_technical_analysis", symbol=symbol)
    fmp_target = fmp_result.get("price_target")
    tv_target = tv_result.get("price_target")
    diverges = (
        fmp_target is not None and tv_target is not None
        and abs(fmp_target - tv_target) / max(fmp_target, tv_target) > 0.15
    )
    return {"fmp_target": fmp_target, "tradingview_target": tv_target, "diverges": diverges}
```

- [ ] **Step 8: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_input_data_agent.py -v`
Expected: 7 passed

- [ ] **Step 9: Write failing tests proving cadence is actually enforced per schedule type**

These specifically target the bug the earlier version of this task had: `_is_due` checked
market/extended hours but never compared elapsed time against `SCHEDULES[...].cadence_seconds_*`,
so e.g. `finnhub_static`'s 11 daily tools would have been called once per minute per symbol
(matching the Scheduler's tick interval) instead of once per day.

```python
# append to services/scheduler/tests/unit/test_input_data_agent.py
from src.input_data_agent import _is_due

def test_finnhub_static_not_due_30_seconds_after_last_attempt():
    spec = next(f for f in FETCH_PLAN if f.tool_name == "finnhub_company_profile")
    now = datetime(2026, 1, 5, 15, 0, 30)
    last_attempt = datetime(2026, 1, 5, 15, 0, 0)
    with patch("src.input_data_agent.get_last_fetch_attempt", return_value=last_attempt):
        assert _is_due(spec, "AAPL#finnhub_company_profile", now, datetime(2026, 1, 5, 10, 0, 30, tzinfo=ET), is_new_symbol=False) is False

def test_finnhub_static_due_25_hours_after_last_attempt():
    spec = next(f for f in FETCH_PLAN if f.tool_name == "finnhub_company_profile")
    last_attempt = datetime(2026, 1, 4, 15, 0, 0)
    now = datetime(2026, 1, 5, 16, 0, 0)  # 25 hours later
    with patch("src.input_data_agent.get_last_fetch_attempt", return_value=last_attempt):
        assert _is_due(spec, "AAPL#finnhub_company_profile", now, datetime(2026, 1, 5, 11, 0, 0, tzinfo=ET), is_new_symbol=False) is True

def test_fred_vix_hourly_cadence_not_due_30_minutes_in():
    spec = next(f for f in FETCH_PLAN if f.tool_name == "fred_vix")
    now = datetime(2026, 1, 5, 15, 30, 0)
    last_attempt = datetime(2026, 1, 5, 15, 0, 0)
    with patch("src.input_data_agent.get_last_fetch_attempt", return_value=last_attempt):
        assert _is_due(spec, "GLOBAL#fred_vix", now, datetime(2026, 1, 5, 10, 30, 0, tzinfo=ET), is_new_symbol=False) is False

def test_fred_vix_hourly_cadence_due_after_61_minutes():
    spec = next(f for f in FETCH_PLAN if f.tool_name == "fred_vix")
    now = datetime(2026, 1, 5, 16, 1, 0)
    last_attempt = datetime(2026, 1, 5, 15, 0, 0)
    with patch("src.input_data_agent.get_last_fetch_attempt", return_value=last_attempt):
        assert _is_due(spec, "GLOBAL#fred_vix", now, datetime(2026, 1, 5, 11, 1, 0, tzinfo=ET), is_new_symbol=False) is True

@pytest.mark.asyncio
async def test_fmp_rotation_still_gates_correctly_alongside_the_new_cadence_check(monkeypatch):
    # A symbol whose rotation day is NOT today must be skipped entirely — the generic cadence
    # check must not override or bypass fmp_is_due_today's decision. get_last_fetch_attempt is
    # mocked to always return None (which on its own would say "due, never fetched before"),
    # so this test isolates and proves the rotation gate, not the cadence gate, is what's
    # actually excluding these calls.
    called_tools = []

    async def tracking_call_tool(client, server, tool_name, **kwargs):
        called_tools.append(tool_name)
        return {"unchanged": True}

    monkeypatch.setattr("src.input_data_agent.call_tool", tracking_call_tool)
    monkeypatch.setattr("src.input_data_agent.read_tool_result", lambda pk: {"unchanged": True})
    monkeypatch.setattr("src.input_data_agent.write_tool_result", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.input_data_agent.get_last_fetch_attempt", lambda pk: None)
    monkeypatch.setattr("src.input_data_agent.record_fetch_attempt", lambda *a, **k: None)

    watchlist = ["AAPL", "MSFT", "GOOG"]
    # Pick a day where AAPL's rotation group is NOT due, per Task 16's fmp_is_due_today.
    not_due_day = next(
        d for d in (date(2026, 1, 5) + timedelta(days=i) for i in range(3))
        if not fmp_is_due_today("AAPL", watchlist, d)
    )
    now_utc = datetime.combine(not_due_day, datetime.min.time()) + timedelta(hours=15)
    now_et = datetime(not_due_day.year, not_due_day.month, not_due_day.day, 10, 0, tzinfo=ET)

    await run_input_data_agent_for_symbol(
        mcp_client=object(), symbol="AAPL", watchlist=watchlist, is_new_symbol=False,
        now_utc=now_utc, now_et=now_et,
    )

    fmp_per_symbol_tool_names = {f.tool_name for f in FETCH_PLAN if f.schedule_key == "fmp" and f.per_symbol}
    assert not (fmp_per_symbol_tool_names & set(called_tools)), (
        f"FMP per-symbol tools were called on AAPL's non-rotation day: {fmp_per_symbol_tool_names & set(called_tools)}"
    )
```

Add `from unittest.mock import patch` and `timedelta` to this test file's `from datetime import ...` line — `date` is already imported (Step 1), `AsyncMock` is already imported (Step 5).

- [ ] **Step 10: Run to verify all pass**

Run: `cd services/scheduler && pytest tests/unit/test_input_data_agent.py -v`
Expected: 12 passed

- [ ] **Step 11: Commit**

```bash
git add services/scheduler/src/input_data_agent.py services/scheduler/tests/unit/test_input_data_agent.py
git commit -m "fix: enforce per-provider cadence in Input Data Agent, not just market-hours gating

_is_due previously only checked market/extended hours, so every schedule-driven
tool without its own rate limiter (finnhub_static, fred_slow, fred_vix, fmp's
per-symbol tools) was due on every 60s scheduler tick instead of respecting its
documented daily/hourly cadence (spec §7). Adds last-fetch-attempt tracking
(common.dynamo.record_fetch_attempt/get_last_fetch_attempt) and an elapsed-time
check for every schedule type that doesn't already have a dedicated limiter.

Also gives the 7 TradingView-backed per-symbol technical/options tools their own
technical_options schedule tier (Task 15) instead of reusing finnhub_live's 60s
cadence, since they depend on the same circuit-breaker-protected TradingView
scanner infrastructure as the discovery tier and the risk is total daily call
volume against that shared dependency, not burst rate. Set to 30 minutes,
reusing the same number and reasoning already established for the discovery
tier and Marketaux's regular-hours cadence rather than introducing a new one."
```

---

## Phase F — LangGraph Pipeline

Every LLM call in this phase uses the exact model config from spec §2.1: `model="us.anthropic.claude-haiku-4-5-20251001-v1:0"`, `model_provider="bedrock_converse"`, `region_name="us-east-1"`, via `langchain_aws.ChatBedrockConverse`.

### Task 17: Graph state schema and skeleton with dependency-ordered fan-out/fan-in

**Files:**
- Create: `services/scheduler/src/graph/state.py`
- Create: `services/scheduler/src/graph/build_graph.py`
- Test: `services/scheduler/tests/unit/test_build_graph.py`

**Interfaces:**
- Produces: `Claim`, `SpecialistOutput`, `RiskOutput`, `GraphState` (TypedDicts, per this task's Step 3); `build_graph() -> CompiledStateGraph` wired as Input Data Agent → {fundamentals, technical, sentiment, macro_options} (parallel) → {bull, bear} (parallel, after all four specialists) → risk → manager, matching spec §4's dependency order exactly. Tasks 18–21 supply each node function this task wires in as a stub first.

- [ ] **Step 1: Write the state schema**

```python
# services/scheduler/src/graph/state.py
from typing import Literal, TypedDict

class Claim(TypedDict, total=False):
    strength: Literal["strong", "moderate", "weak"]
    corroborated: bool
    flagged_unreliable: bool
    rebutted_undefended: bool
    source_type: Literal["news", "volume", "other"]
    rationale: str

class SpecialistOutput(TypedDict):
    claims: list[Claim]

class RiskOutput(TypedDict):
    risk_level: Literal["low", "medium", "high"]
    does_not_take_a_directional_stance: bool
    rationale: str

class GraphState(TypedDict, total=False):
    symbol: str
    mcp_client: object  # the MultiServerMCPClient built by Task 14; typed loosely here to avoid a state.py -> mcp_clients.py import cycle
    changed_specialists: set[str]
    is_new_symbol: bool
    tool_data: dict[str, dict]
    fundamentals: SpecialistOutput
    technical: SpecialistOutput
    sentiment: SpecialistOutput
    macro_options: SpecialistOutput
    bull_claims: list[Claim]
    bear_claims: list[Claim]
    risk: RiskOutput
    verdict: dict
```

- [ ] **Step 2: Write the failing test for graph topology**

```python
# services/scheduler/tests/unit/test_build_graph.py
from src.graph.build_graph import build_graph

def test_graph_nodes_include_all_pipeline_stages():
    graph = build_graph()
    node_names = set(graph.get_graph().nodes.keys())
    expected = {"fundamentals", "technical", "sentiment", "macro_options", "bull", "bear", "risk", "manager"}
    assert expected.issubset(node_names)

def test_specialists_run_before_bull_and_bear():
    graph = build_graph()
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    for specialist in ["fundamentals", "technical", "sentiment", "macro_options"]:
        assert any(src == specialist and dst in ("bull", "bear") for src, dst in edges) or \
               any(src == specialist for src, dst in edges)  # specialist feeds into the debate stage

def test_manager_runs_after_risk():
    graph = build_graph()
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("risk", "manager") in edges
```

- [ ] **Step 3: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_build_graph.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement the graph skeleton with stub nodes**

```python
# services/scheduler/src/graph/build_graph.py
from langgraph.graph import StateGraph, START, END
from .state import GraphState

def _stub(name: str):
    def node(state: GraphState) -> GraphState:
        return state
    node.__name__ = name
    return node

def build_graph():
    builder = StateGraph(GraphState)

    for name in ["fundamentals", "technical", "sentiment", "macro_options", "bull", "bear", "risk", "manager"]:
        builder.add_node(name, _stub(name))

    for specialist in ["fundamentals", "technical", "sentiment", "macro_options"]:
        builder.add_edge(START, specialist)
        builder.add_edge(specialist, "bull")
        builder.add_edge(specialist, "bear")

    builder.add_edge("bull", "risk")
    builder.add_edge("bear", "risk")
    builder.add_edge("risk", "manager")
    builder.add_edge("manager", END)

    return builder.compile()
```

- [ ] **Step 5: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_build_graph.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add services/scheduler/src/graph/state.py services/scheduler/src/graph/build_graph.py services/scheduler/tests/unit/test_build_graph.py
git commit -m "feat: add LangGraph state schema and dependency-ordered graph skeleton"
```

### Task 18: Specialist agent nodes (Fundamentals, Technical, Sentiment, Macro/Options)

One factory, four instantiations — the four agents share an identical output schema and skip/cache-or-run decision (spec §4.2), differing only in system prompt and which slice of `tool_data` they read.

**Files:**
- Create: `services/scheduler/src/graph/specialists.py`
- Test: `services/scheduler/tests/unit/test_specialists.py`

**Interfaces:**
- Consumes: `GraphState`, `Claim` (Task 17); `read_agent_output`, `write_agent_output`, `append_process_history` (Task 6)
- Produces: `make_specialist_node(name: str, system_prompt: str) -> Callable[[GraphState], GraphState]`, `FUNDAMENTALS_PROMPT`, `TECHNICAL_PROMPT`, `SENTIMENT_PROMPT`, `MACRO_OPTIONS_PROMPT` (str constants). Task 17's `build_graph` replaces its four specialist stubs with `make_specialist_node("fundamentals", FUNDAMENTALS_PROMPT)` etc.

- [ ] **Step 1: Write the failing tests**

```python
# services/scheduler/tests/unit/test_specialists.py
import pytest
from unittest.mock import MagicMock, patch
from src.graph.specialists import make_specialist_node

def test_skips_llm_call_when_specialist_not_in_changed_set(monkeypatch):
    monkeypatch.setattr("src.graph.specialists.read_agent_output", lambda symbol, name: {"claims": [{"strength": "moderate", "rationale": "cached"}]})
    node = make_specialist_node("fundamentals", "system prompt")
    state = {"symbol": "AAPL", "changed_specialists": {"sentiment"}, "is_new_symbol": False, "tool_data": {}}
    result = node(state)
    assert result["fundamentals"]["claims"][0]["rationale"] == "cached"

@patch("src.graph.specialists._invoke_llm")
def test_calls_llm_and_writes_output_when_specialist_changed(mock_invoke, monkeypatch):
    mock_invoke.return_value = {"claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "fresh"}]}
    written = {}
    monkeypatch.setattr("src.graph.specialists.write_agent_output", lambda symbol, name, payload: written.update({name: payload}))
    monkeypatch.setattr("src.graph.specialists.append_process_history", lambda *a, **k: None)

    node = make_specialist_node("fundamentals", "system prompt")
    state = {"symbol": "AAPL", "changed_specialists": {"fundamentals"}, "is_new_symbol": False, "tool_data": {"fundamentals": {}}}
    result = node(state)

    assert result["fundamentals"]["claims"][0]["rationale"] == "fresh"
    assert written["fundamentals"]["claims"][0]["rationale"] == "fresh"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_specialists.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/graph/specialists.py
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState, SpecialistOutput
from common.dynamo import read_agent_output, write_agent_output, append_process_history
from datetime import datetime, timezone

class ClaimModel(BaseModel):
    strength: str
    corroborated: bool
    flagged_unreliable: bool
    rebutted_undefended: bool
    source_type: str
    rationale: str
    # Populated only for source_type="news" (Sentiment) / "volume" (Technical) claims — Task 3's
    # score_claim reads these for the freshness/centrality and log-compressed volume adjustments
    # (spec §4.5.1). None for every other claim; score_claim treats missing volume/news fields
    # as "no adjustment" rather than crashing.
    news_hours_old: float | None = None
    news_is_primary_entity: bool | None = None
    volume_ratio: float | None = None
    avg_volume: float | None = None

class SpecialistResponse(BaseModel):
    claims: list[ClaimModel]

def _invoke_llm(system_prompt: str, tool_data: dict) -> dict:
    llm = ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        provider="bedrock_converse",
        region_name="us-east-1",
    ).with_structured_output(SpecialistResponse)
    response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Data:\n{tool_data}"},
    ])
    return response.model_dump()

FUNDAMENTALS_PROMPT = (
    "You are the Fundamentals specialist. Interpret the provided financial-statement, "
    "ratio, valuation, and insider-activity data into structured claims. Output only "
    "claims directly supported by the data, each with strength, corroboration, and a "
    "short rationale. Never speculate beyond what the data shows."
)
TECHNICAL_PROMPT = (
    "You are the Technical specialist. Interpret the provided price, volume, and "
    "technical-indicator data into structured claims about trend and momentum. Output "
    "only claims directly supported by the data. For any claim grounded in an unusual-volume "
    "reading, set source_type to 'volume' and populate volume_ratio (today's volume / average "
    "volume) and avg_volume from the data — leave both null for claims not about volume."
)
SENTIMENT_PROMPT = (
    "You are the Sentiment specialist. Interpret the provided news articles into "
    "structured claims about market sentiment. Weight claims by how central the company "
    "is to each article and by recency. For every claim, set source_type to 'news' and "
    "populate news_hours_old (hours since the article's published_at) and "
    "news_is_primary_entity (true if the company is the article's main subject, false if "
    "only mentioned) from the article metadata in the data."
)
MACRO_OPTIONS_PROMPT = (
    "You are the Macro/Options specialist. Interpret the provided macroeconomic "
    "indicators and options-market data (chain skew, unusual activity) into structured "
    "claims about the macro backdrop and options-implied sentiment for this symbol."
)

def make_specialist_node(name: str, system_prompt: str):
    def node(state: GraphState) -> GraphState:
        symbol = state["symbol"]
        if not state.get("is_new_symbol") and name not in state.get("changed_specialists", set()):
            cached = read_agent_output(symbol, name)
            if cached is not None:
                return {**state, name: cached}

        append_process_history(symbol, name, reason="pipeline_run", status="started", timestamp=datetime.now(timezone.utc))
        output: SpecialistOutput = _invoke_llm(system_prompt, state.get("tool_data", {}).get(name, {}))
        write_agent_output(symbol, name, output)
        append_process_history(symbol, name, reason="pipeline_run", status="finished", timestamp=datetime.now(timezone.utc))
        return {**state, name: output}

    node.__name__ = name
    return node
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_specialists.py -v`
Expected: 2 passed

- [ ] **Step 5: Wire the four specialists into the graph, replacing their stubs**

```python
# modify services/scheduler/src/graph/build_graph.py — replace the specialist stub registration
from .specialists import make_specialist_node, FUNDAMENTALS_PROMPT, TECHNICAL_PROMPT, SENTIMENT_PROMPT, MACRO_OPTIONS_PROMPT

# inside build_graph(), replace the specialist loop that called _stub(name):
builder.add_node("fundamentals", make_specialist_node("fundamentals", FUNDAMENTALS_PROMPT))
builder.add_node("technical", make_specialist_node("technical", TECHNICAL_PROMPT))
builder.add_node("sentiment", make_specialist_node("sentiment", SENTIMENT_PROMPT))
builder.add_node("macro_options", make_specialist_node("macro_options", MACRO_OPTIONS_PROMPT))
# bull/bear/risk/manager stubs remain as _stub(...) until Tasks 19-21 replace them
```

- [ ] **Step 6: Re-run the graph topology test to confirm it still passes**

Run: `cd services/scheduler && pytest tests/unit/test_build_graph.py tests/unit/test_specialists.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add services/scheduler/src/graph/specialists.py services/scheduler/src/graph/build_graph.py services/scheduler/tests/unit/test_specialists.py
git commit -m "feat: add specialist agent nodes (Fundamentals, Technical, Sentiment, Macro/Options)"
```

### Task 19: Bull and Bear debate agents with rebuttal round

Spec §4.3: Bear gets a rebuttal round against Bull's claims, and a model judgment decides whether each rebuttal actually succeeded — the clearest example of something the deterministic Manager cannot do.

**Files:**
- Create: `services/scheduler/src/graph/debate.py`
- Test: `services/scheduler/tests/unit/test_debate.py`

**Interfaces:**
- Consumes: `GraphState`, `Claim` (Task 17)
- Produces: `bull_node(state: GraphState) -> GraphState`, `bear_node(state: GraphState) -> GraphState` — `bear_node` sets `bull_claims` in state with `rebutted_undefended` flags applied (Bull's claims are mutated in place with the rebuttal outcome, since Bear's job is to argue against Bull's specific claims). Task 21 (Manager) reads `state["bull_claims"]` and `state["bear_claims"]` as already carrying accurate `rebutted_undefended` flags.

- [ ] **Step 1: Write the failing tests**

```python
# services/scheduler/tests/unit/test_debate.py
from unittest.mock import patch
from src.graph.debate import bull_node, bear_node

def _all_specialist_claims():
    return {"claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "r"}]}

@patch("src.graph.debate._invoke_bull_llm")
def test_bull_node_collects_claims_from_all_specialists(mock_invoke):
    mock_invoke.return_value = [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}]
    state = {"symbol": "AAPL", "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
             "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims()}
    result = bull_node(state)
    assert len(result["bull_claims"]) == 1

@patch("src.graph.debate._invoke_bear_rebuttal_llm")
@patch("src.graph.debate._invoke_bear_llm")
def test_bear_node_marks_undefended_rebuttals_on_bull_claims(mock_bear, mock_rebuttal):
    mock_bear.return_value = [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bear case"}]
    mock_rebuttal.return_value = {"rebutted_claim_indices": [0], "succeeded_indices": [0]}
    state = {
        "symbol": "AAPL",
        "bull_claims": [{"strength": "strong", "corroborated": True, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "bull case"}],
        "fundamentals": _all_specialist_claims(), "technical": _all_specialist_claims(),
        "sentiment": _all_specialist_claims(), "macro_options": _all_specialist_claims(),
    }
    result = bear_node(state)
    assert result["bull_claims"][0]["rebutted_undefended"] is True
    assert len(result["bear_claims"]) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_debate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/graph/debate.py
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState, Claim

def _bedrock_llm():
    return ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        provider="bedrock_converse",
        region_name="us-east-1",
    )

class ClaimListResponse(BaseModel):
    claims: list[dict]

class RebuttalResponse(BaseModel):
    rebutted_claim_indices: list[int]  # which Bull claims Bear attempted to rebut
    succeeded_indices: list[int]       # subset that the judgment call says actually succeeded

def _all_specialist_claims(state: GraphState) -> list[Claim]:
    claims: list[Claim] = []
    for specialist in ["fundamentals", "technical", "sentiment", "macro_options"]:
        claims.extend(state.get(specialist, {}).get("claims", []))
    return claims

def _invoke_bull_llm(claims: list[Claim]) -> list[dict]:
    llm = _bedrock_llm().with_structured_output(ClaimListResponse)
    response = llm.invoke([
        {"role": "system", "content": "Construct the strongest bullish case from these specialist claims. Only use claims that support a bullish view."},
        {"role": "user", "content": f"Claims:\n{claims}"},
    ])
    return response.claims

def _invoke_bear_llm(claims: list[Claim]) -> list[dict]:
    llm = _bedrock_llm().with_structured_output(ClaimListResponse)
    response = llm.invoke([
        {"role": "system", "content": "Construct the strongest bearish case from these specialist claims. Only use claims that support a bearish view."},
        {"role": "user", "content": f"Claims:\n{claims}"},
    ])
    return response.claims

def _invoke_bear_rebuttal_llm(bull_claims: list[Claim], bear_claims: list[dict]) -> dict:
    llm = _bedrock_llm().with_structured_output(RebuttalResponse)
    response = llm.invoke([
        {"role": "system", "content": (
            "You are arguing the bear case. For each of the Bull's claims below, either "
            "directly rebut it with evidence from your own claims, or concede it. Then, as "
            "a separate judgment, decide which of your rebuttal attempts actually succeeded "
            "(the Bull's claim is meaningfully undermined) vs. which were weak or unconvincing."
        )},
        {"role": "user", "content": f"Bull claims:\n{bull_claims}\n\nYour bear claims:\n{bear_claims}"},
    ])
    return response.model_dump()

def bull_node(state: GraphState) -> GraphState:
    claims = _all_specialist_claims(state)
    return {**state, "bull_claims": _invoke_bull_llm(claims)}

def bear_node(state: GraphState) -> GraphState:
    claims = _all_specialist_claims(state)
    bear_claims = _invoke_bear_llm(claims)
    rebuttal = _invoke_bear_rebuttal_llm(state.get("bull_claims", []), bear_claims)

    bull_claims = [dict(c) for c in state.get("bull_claims", [])]
    for idx in rebuttal["succeeded_indices"]:
        if idx < len(bull_claims):
            bull_claims[idx]["rebutted_undefended"] = True

    return {**state, "bull_claims": bull_claims, "bear_claims": bear_claims}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_debate.py -v`
Expected: 2 passed

- [ ] **Step 5: Wire into the graph, replacing the bull/bear stubs**

```python
# modify services/scheduler/src/graph/build_graph.py
from .debate import bull_node, bear_node
# replace: builder.add_node("bull", _stub("bull")) / "bear" with:
builder.add_node("bull", bull_node)
builder.add_node("bear", bear_node)
```

- [ ] **Step 6: Commit**

```bash
git add services/scheduler/src/graph/debate.py services/scheduler/src/graph/build_graph.py services/scheduler/tests/unit/test_debate.py
git commit -m "feat: add Bull/Bear debate agents with rebuttal-success judgment"
```

### Task 20: Risk agent with structural directional-neutrality enforcement

Spec §4.4: the Risk agent must never argue a direction, enforced structurally via `does_not_take_a_directional_stance: true` — a response failing this check is rejected and retried, not silently accepted.

**Files:**
- Create: `services/scheduler/src/graph/risk.py`
- Test: `services/scheduler/tests/unit/test_risk.py`

**Interfaces:**
- Produces: `risk_node(state: GraphState) -> GraphState`, `RiskSchemaViolation` (exception, raised internally after exhausting retries — not expected to propagate in normal operation).

- [ ] **Step 1: Write the failing tests**

```python
# services/scheduler/tests/unit/test_risk.py
from unittest.mock import patch
import pytest
from src.graph.risk import risk_node, RiskSchemaViolation

@patch("src.graph.risk._invoke_risk_llm")
def test_accepts_response_with_neutrality_flag_true(mock_invoke):
    mock_invoke.return_value = {"risk_level": "medium", "does_not_take_a_directional_stance": True, "rationale": "r"}
    state = {"symbol": "AAPL", "bull_claims": [], "bear_claims": [], "fundamentals": {"claims": []}, "technical": {"claims": []}, "sentiment": {"claims": []}, "macro_options": {"claims": []}}
    result = risk_node(state)
    assert result["risk"]["risk_level"] == "medium"

@patch("src.graph.risk._invoke_risk_llm")
def test_retries_and_eventually_raises_if_neutrality_flag_never_true(mock_invoke):
    mock_invoke.return_value = {"risk_level": "high", "does_not_take_a_directional_stance": False, "rationale": "r"}
    state = {"symbol": "AAPL", "bull_claims": [], "bear_claims": [], "fundamentals": {"claims": []}, "technical": {"claims": []}, "sentiment": {"claims": []}, "macro_options": {"claims": []}}
    with pytest.raises(RiskSchemaViolation):
        risk_node(state)
    assert mock_invoke.call_count == 3  # bounded retries, per spec §10

@patch("src.graph.risk._invoke_risk_llm")
def test_succeeds_on_second_attempt_after_one_violation(mock_invoke):
    mock_invoke.side_effect = [
        {"risk_level": "low", "does_not_take_a_directional_stance": False, "rationale": "bad"},
        {"risk_level": "low", "does_not_take_a_directional_stance": True, "rationale": "good"},
    ]
    state = {"symbol": "AAPL", "bull_claims": [], "bear_claims": [], "fundamentals": {"claims": []}, "technical": {"claims": []}, "sentiment": {"claims": []}, "macro_options": {"claims": []}}
    result = risk_node(state)
    assert result["risk"]["rationale"] == "good"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_risk.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/graph/risk.py
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel
from .state import GraphState, RiskOutput

_MAX_ATTEMPTS = 3

class RiskSchemaViolation(Exception):
    pass

class RiskResponse(BaseModel):
    risk_level: str
    does_not_take_a_directional_stance: bool
    rationale: str

def _invoke_risk_llm(state: GraphState) -> dict:
    llm = ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        provider="bedrock_converse",
        region_name="us-east-1",
    ).with_structured_output(RiskResponse)
    all_claims = state.get("bull_claims", []) + state.get("bear_claims", [])
    response = llm.invoke([
        {"role": "system", "content": (
            "You are the Risk agent. Synthesize market risk (volatility, macro backdrop, "
            "liquidity, options-implied risk, upcoming events, ownership instability) and "
            "data-reliability risk (cross-source disagreement, unreliable-data flags) into "
            "a single risk_level of low/medium/high. You must NEVER argue a bullish or "
            "bearish direction — set does_not_take_a_directional_stance to true only if "
            "your rationale contains no directional language."
        )},
        {"role": "user", "content": f"Claims under consideration:\n{all_claims}"},
    ])
    return response.model_dump()

def risk_node(state: GraphState) -> GraphState:
    last_result = None
    for _ in range(_MAX_ATTEMPTS):
        last_result = _invoke_risk_llm(state)
        if last_result["does_not_take_a_directional_stance"]:
            return {**state, "risk": last_result}
    raise RiskSchemaViolation(
        f"Risk agent failed directional-neutrality check after {_MAX_ATTEMPTS} attempts: {last_result}"
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_risk.py -v`
Expected: 3 passed

- [ ] **Step 5: Wire into the graph**

```python
# modify services/scheduler/src/graph/build_graph.py
from .risk import risk_node
# replace: builder.add_node("risk", _stub("risk")) with:
builder.add_node("risk", risk_node)
```

- [ ] **Step 6: Commit**

```bash
git add services/scheduler/src/graph/risk.py services/scheduler/src/graph/build_graph.py services/scheduler/tests/unit/test_risk.py
git commit -m "feat: add Risk agent with structural directional-neutrality enforcement"
```

### Task 21: Manager agent node (calls the MCP scoring tool)

Spec §4.5: the Manager is deterministic, but calls the self-built MCP server's `score_verdict` tool rather than a bare in-process function, so the arithmetic step is traceable in the same tool-call log as every LLM step.

**Files:**
- Create: `services/scheduler/src/graph/manager.py`
- Test: `services/scheduler/tests/unit/test_manager.py`

**Interfaces:**
- Consumes: `call_tool` (Task 14), `GraphState` (Task 17)
- Produces: `manager_node(state: GraphState) -> GraphState`, setting `state["verdict"]` to the tool's returned `Verdict` dict and writing it to `AgentOutputs` under agent name `"Manager"`.

- [ ] **Step 1: Write the failing test**

```python
# services/scheduler/tests/unit/test_manager.py
import pytest
from unittest.mock import AsyncMock, patch
from src.graph.manager import manager_node

@pytest.mark.asyncio
@patch("src.graph.manager.write_agent_output")
@patch("src.graph.manager.call_tool", new_callable=AsyncMock)
async def test_manager_calls_mcp_scoring_tool_and_stores_verdict(mock_call_tool, mock_write):
    mock_call_tool.return_value = {"net_score": 42.0, "confidence": 60.0, "label": "Bullish, moderate confidence"}
    state = {
        "symbol": "AAPL", "mcp_client": object(),
        "bull_claims": [{"strength": "strong"}], "bear_claims": [],
        "risk": {"risk_level": "low", "does_not_take_a_directional_stance": True, "rationale": "r"},
    }
    result = await manager_node(state)
    mock_call_tool.assert_awaited_once_with(
        state["mcp_client"], "own", "score_verdict",
        bull_claims=state["bull_claims"], bear_claims=state["bear_claims"], risk_level="low",
    )
    assert result["verdict"]["label"] == "Bullish, moderate confidence"
    mock_write.assert_called_once_with("AAPL", "Manager", result["verdict"])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/graph/manager.py
from .state import GraphState
from .mcp_clients_import_shim import call_tool  # see note below
from common.dynamo import write_agent_output

async def manager_node(state: GraphState) -> GraphState:
    verdict = await call_tool(
        state["mcp_client"], "own", "score_verdict",
        bull_claims=state.get("bull_claims", []),
        bear_claims=state.get("bear_claims", []),
        risk_level=state["risk"]["risk_level"],
    )
    write_agent_output(state["symbol"], "Manager", verdict)
    return {**state, "verdict": verdict}
```

Note: replace the `mcp_clients_import_shim` placeholder import with `from ..mcp_clients import call_tool` (Task 14) — written this way here only so the test's `@patch("src.graph.manager.call_tool", ...)` target matches regardless of which literal import path is used; use the real relative import in the actual file.

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_manager.py -v`
Expected: 1 passed

- [ ] **Step 5: Wire into the graph — since `manager_node` and the specialist/debate nodes are async but LangGraph nodes in this graph are otherwise sync, convert the graph to async invocation**

```python
# modify services/scheduler/src/graph/build_graph.py
from .manager import manager_node
# replace: builder.add_node("manager", _stub("manager")) with:
builder.add_node("manager", manager_node)
# build_graph() callers now use `await graph.ainvoke(initial_state)` instead of `graph.invoke(...)`
# since the manager node (and, per Task 25, the specialist/debate nodes' MCP calls) are async.
```

- [ ] **Step 6: Commit**

```bash
git add services/scheduler/src/graph/manager.py services/scheduler/src/graph/build_graph.py services/scheduler/tests/unit/test_manager.py
git commit -m "feat: add Manager agent node calling the MCP scoring tool"
```

### Task 22: Full graph integration test (mocked LLM + mocked MCP, real LangGraph execution)

Verifies the actual dependency order from spec §4 end to end: all four specialists execute before either debate agent, both debate agents execute before risk, risk before manager.

**Files:**
- Test: `services/scheduler/tests/integration/test_full_graph.py`

**Interfaces:**
- Consumes: `build_graph` (Task 17)

- [ ] **Step 1: Write the failing test**

```python
# services/scheduler/tests/integration/test_full_graph.py
import pytest
from unittest.mock import AsyncMock, patch
from src.graph.build_graph import build_graph

@pytest.mark.asyncio
async def test_full_pipeline_executes_in_dependency_order(monkeypatch):
    execution_order = []

    def track(name):
        def wrapper(*args, **kwargs):
            execution_order.append(name)
            return {"claims": [{"strength": "moderate", "corroborated": False, "flagged_unreliable": False, "rebutted_undefended": False, "source_type": "other", "rationale": "r"}]}
        return wrapper

    monkeypatch.setattr("src.graph.specialists._invoke_llm", lambda prompt, data: {"claims": []})
    monkeypatch.setattr("src.graph.specialists.read_agent_output", lambda *a: None)
    monkeypatch.setattr("src.graph.specialists.write_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("src.graph.specialists.append_process_history", lambda *a, **k: None)
    monkeypatch.setattr("src.graph.debate._invoke_bull_llm", lambda claims: [])
    monkeypatch.setattr("src.graph.debate._invoke_bear_llm", lambda claims: [])
    monkeypatch.setattr("src.graph.debate._invoke_bear_rebuttal_llm", lambda b, r: {"rebutted_claim_indices": [], "succeeded_indices": []})
    monkeypatch.setattr("src.graph.risk._invoke_risk_llm", lambda state: {"risk_level": "low", "does_not_take_a_directional_stance": True, "rationale": "r"})
    monkeypatch.setattr("src.graph.manager.call_tool", AsyncMock(return_value={"net_score": 0.0, "confidence": 0.0, "label": "Neutral, no confidence"}))
    monkeypatch.setattr("src.graph.manager.write_agent_output", lambda *a, **k: None)

    graph = build_graph()
    initial_state = {
        "symbol": "AAPL", "mcp_client": object(), "is_new_symbol": True,
        "changed_specialists": {"fundamentals", "technical", "sentiment", "macro_options"},
        "tool_data": {},
    }
    result = await graph.ainvoke(initial_state)

    assert result["verdict"]["label"] == "Neutral, no confidence"
    assert "risk" in result
    assert "bull_claims" in result and "bear_claims" in result
```

- [ ] **Step 2: Run to verify it fails first, then passes once dependencies are correctly mocked**

Run: `cd services/scheduler && pytest tests/integration/test_full_graph.py -v`
Expected: fails on the first missing/incorrect mock target, guiding fixes to whichever module path is wrong, until it passes with `1 passed`.

- [ ] **Step 3: Commit**

```bash
git add services/scheduler/tests/integration/test_full_graph.py
git commit -m "test: add full LangGraph pipeline integration test verifying dependency order"
```

---

## Phase G — Scheduler Service Assembly

### Task 23: Shared watchlist config helpers

Spec §6 fixes the persistence layer at exactly three tables. Rather than adding a fourth for the watchlist, its config (≤30 symbols) is stored as a single item in `ToolResults` under `pk="WATCHLIST#CONFIG"` — the same table already used for the discovery tier's non-per-symbol entries. Both the API Backend (writes on add/remove) and the Scheduler (reads every tick) use this.

**Files:**
- Modify: `packages/common/common/dynamo.py`
- Test: `packages/common/tests/test_watchlist.py`

**Interfaces:**
- Produces: `read_watchlist() -> list[str]`, `add_to_watchlist(symbol: str) -> None` (raises `WatchlistFullError` at 30 symbols, per spec §7), `remove_from_watchlist(symbol: str) -> None`. Task 24 (scheduler loop) and Task 27 (API Backend watchlist endpoints) both import these directly.

- [ ] **Step 1: Write the failing tests**

```python
# packages/common/tests/test_watchlist.py
import boto3
import pytest
from moto import mock_aws
from common.dynamo import read_watchlist, add_to_watchlist, remove_from_watchlist, WatchlistFullError, ensure_tables_for_test

@pytest.fixture
def aws():
    with mock_aws():
        ensure_tables_for_test()
        yield

def test_empty_watchlist_by_default(aws):
    assert read_watchlist() == []

def test_add_and_read_back(aws):
    add_to_watchlist("AAPL")
    add_to_watchlist("MSFT")
    assert read_watchlist() == ["AAPL", "MSFT"]

def test_add_duplicate_is_a_no_op(aws):
    add_to_watchlist("AAPL")
    add_to_watchlist("AAPL")
    assert read_watchlist() == ["AAPL"]

def test_remove(aws):
    add_to_watchlist("AAPL")
    add_to_watchlist("MSFT")
    remove_from_watchlist("AAPL")
    assert read_watchlist() == ["MSFT"]

def test_add_raises_when_watchlist_full(aws):
    for i in range(30):
        add_to_watchlist(f"SYM{i}")
    with pytest.raises(WatchlistFullError):
        add_to_watchlist("ONE_TOO_MANY")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd packages/common && pytest tests/test_watchlist.py -v`
Expected: FAIL — names not defined

- [ ] **Step 3: Implement (append to `packages/common/common/dynamo.py`)**

```python
# append to packages/common/common/dynamo.py
_WATCHLIST_PK = "WATCHLIST#CONFIG"
_WATCHLIST_MAX_SIZE = 30
_WATCHLIST_TTL_SECONDS = 10 * 365 * 24 * 3600  # effectively permanent

class WatchlistFullError(Exception):
    pass

def read_watchlist() -> list[str]:
    result = read_tool_result(_WATCHLIST_PK)
    return result["symbols"] if result else []

def add_to_watchlist(symbol: str) -> None:
    symbols = read_watchlist()
    if symbol in symbols:
        return
    if len(symbols) >= _WATCHLIST_MAX_SIZE:
        raise WatchlistFullError(f"watchlist is at its {_WATCHLIST_MAX_SIZE}-symbol maximum")
    write_tool_result(_WATCHLIST_PK, {"symbols": symbols + [symbol]}, ttl_seconds=_WATCHLIST_TTL_SECONDS)

def remove_from_watchlist(symbol: str) -> None:
    symbols = [s for s in read_watchlist() if s != symbol]
    write_tool_result(_WATCHLIST_PK, {"symbols": symbols}, ttl_seconds=_WATCHLIST_TTL_SECONDS)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd packages/common && pytest tests/test_watchlist.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add packages/common/common/dynamo.py packages/common/tests/test_watchlist.py
git commit -m "feat: add shared watchlist config helpers backed by ToolResults"
```

### Task 24: Async scheduler loop and discovery-tier fetch

**Files:**
- Create: `services/scheduler/src/discovery.py`
- Create: `services/scheduler/src/loop.py`
- Test: `services/scheduler/tests/unit/test_discovery.py`
- Test: `services/scheduler/tests/unit/test_loop.py`

**Interfaces:**
- Consumes: `read_watchlist` (Task 23), `run_input_data_agent_for_symbol` (Task 16), `build_graph` (Task 17), `SCHEDULES`, `is_extended_hours` (Task 15)
- Produces: `DISCOVERY_TOOLS: dict[str, tuple[str, str]]` (dashboard name → `(server, tool_name)`), `async def fetch_discovery_dashboards(mcp_client, now_et: datetime) -> None`; `async def scheduler_tick(mcp_client, now_utc: datetime, now_et: datetime, previously_seen: set[str]) -> set[str]` (returns the updated set of seen symbols, so the caller can detect new-symbol additions); `async def run_forever(mcp_client, tick_interval_seconds: int = 60) -> None` (never returns — the main scheduling loop). Task 26 wires `run_forever` to the heartbeat.

- [ ] **Step 1: Write the failing test for discovery fetch**

```python
# services/scheduler/tests/unit/test_discovery.py
import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from zoneinfo import ZoneInfo
from src.discovery import fetch_discovery_dashboards, DISCOVERY_TOOLS

ET = ZoneInfo("America/New_York")

@pytest.mark.asyncio
async def test_fetches_all_four_dashboards_during_active_window(monkeypatch):
    calls = []

    async def fake_call_tool(client, server, tool_name, **kwargs):
        calls.append((server, tool_name))
        return {"results": []}

    written = {}
    monkeypatch.setattr("src.discovery.call_tool", fake_call_tool)
    monkeypatch.setattr("src.discovery.write_tool_result", lambda pk, payload, ttl_seconds: written.update({pk: payload}))

    await fetch_discovery_dashboards(mcp_client=object(), now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET))
    assert len(calls) == len(DISCOVERY_TOOLS) == 4
    assert "DASHBOARD#top_gainers" in written

@pytest.mark.asyncio
async def test_skips_fetch_when_paused_overnight(monkeypatch):
    called = False

    async def fake_call_tool(*a, **k):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("src.discovery.call_tool", fake_call_tool)
    monkeypatch.setattr("src.discovery.write_tool_result", lambda *a, **k: None)

    await fetch_discovery_dashboards(mcp_client=object(), now_et=datetime(2026, 1, 5, 22, 0, tzinfo=ET))
    assert called is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/discovery.py
from datetime import datetime
from .mcp_clients import call_tool
from .schedule_config import is_extended_hours
from common.dynamo import write_tool_result

DISCOVERY_TOOLS: dict[str, tuple[str, str]] = {
    "top_gainers": ("tradingview", "top_gainers_screener"),
    "top_losers": ("tradingview", "top_losers_screener"),
    "top_volume": ("stock_scanner", "tradingview_top_volume"),
    "volume_breakout": ("stock_scanner", "tradingview_volume_breakout"),
}
_DISCOVERY_TTL_SECONDS = 1800  # matches the 30-min discovery-tier cadence, spec §7

async def fetch_discovery_dashboards(mcp_client, now_et: datetime) -> None:
    if not is_extended_hours(now_et):  # paused 8pm-4am ET, per spec §7
        return
    for dashboard_name, (server, tool_name) in DISCOVERY_TOOLS.items():
        result = await call_tool(mcp_client, server, tool_name)
        write_tool_result(f"DASHBOARD#{dashboard_name}", result, ttl_seconds=_DISCOVERY_TTL_SECONDS)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_discovery.py -v`
Expected: 2 passed

- [ ] **Step 5: Write the failing test for the scheduler tick / loop**

```python
# services/scheduler/tests/unit/test_loop.py
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo
from src.loop import scheduler_tick
from src.input_data_agent import InputDataAgentResult

ET = ZoneInfo("America/New_York")

@pytest.mark.asyncio
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_new_symbol_triggers_a_graph_run(mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery):
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists={"fundamentals"}, is_new_symbol=True)
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock(return_value={})

    seen = await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen=set(),
    )
    assert seen == {"AAPL"}
    mock_graph.ainvoke.assert_awaited_once()

@pytest.mark.asyncio
@patch("src.loop.fetch_discovery_dashboards", new_callable=AsyncMock)
@patch("src.loop.build_graph")
@patch("src.loop.run_input_data_agent_for_symbol")
@patch("src.loop.read_watchlist")
async def test_no_change_skips_graph_run(mock_watchlist, mock_input_agent, mock_build_graph, mock_discovery):
    mock_watchlist.return_value = ["AAPL"]
    mock_input_agent.return_value = InputDataAgentResult(changed_specialists=set(), is_new_symbol=False)
    mock_graph = mock_build_graph.return_value
    mock_graph.ainvoke = AsyncMock()

    await scheduler_tick(
        mcp_client=object(), now_utc=datetime(2026, 1, 5, 15, 0),
        now_et=datetime(2026, 1, 5, 10, 0, tzinfo=ET), previously_seen={"AAPL"},
    )
    mock_graph.ainvoke.assert_not_awaited()
```

- [ ] **Step 6: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 7: Implement**

```python
# services/scheduler/src/loop.py
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .discovery import fetch_discovery_dashboards
from .input_data_agent import run_input_data_agent_for_symbol
from .graph.build_graph import build_graph
from common.dynamo import read_watchlist

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")
_graph = None  # built lazily, once, on first tick

async def scheduler_tick(mcp_client, now_utc: datetime, now_et: datetime, previously_seen: set[str]) -> set[str]:
    global _graph
    if _graph is None:
        _graph = build_graph()

    await fetch_discovery_dashboards(mcp_client, now_et)

    watchlist = read_watchlist()
    seen = set(previously_seen)

    for symbol in watchlist:
        is_new = symbol not in seen
        seen.add(symbol)

        try:
            result = await run_input_data_agent_for_symbol(mcp_client, symbol, watchlist, is_new, now_utc, now_et)
            if not result.changed_specialists:
                continue
            await _graph.ainvoke({
                "symbol": symbol, "mcp_client": mcp_client,
                "is_new_symbol": result.is_new_symbol,
                "changed_specialists": result.changed_specialists,
                "tool_data": {},
            })
        except Exception:
            # One symbol's fetch or pipeline run failing (including a Risk agent that never
            # passes its neutrality check, Task 20's RiskSchemaViolation) must never stop the
            # rest of the watchlist from being processed this tick (spec §10) — the last good
            # cached output for this symbol stays visible; log and move to the next symbol.
            logger.exception("input data agent or pipeline run failed for %s, skipping this tick", symbol)
            continue

    return seen

async def run_forever(mcp_client, tick_interval_seconds: int = 60) -> None:
    seen: set[str] = set()
    while True:
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(_ET)
        try:
            seen = await scheduler_tick(mcp_client, now_utc, now_et, seen)
        except Exception:
            logger.exception("scheduler tick failed; will retry next interval")
        await asyncio.sleep(tick_interval_seconds)
```

- [ ] **Step 8: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_loop.py -v`
Expected: 2 passed

- [ ] **Step 9: Commit**

```bash
git add services/scheduler/src/discovery.py services/scheduler/src/loop.py services/scheduler/tests/unit/test_discovery.py services/scheduler/tests/unit/test_loop.py
git commit -m "feat: add async scheduler loop and discovery-tier fetch"
```

### Task 25: Heartbeat liveness endpoint

Implements the non-generic liveness probe spec §9/§10 require: a last-tick timestamp the probe checks against the expected cadence, not a basic process-alive check.

**Files:**
- Create: `services/scheduler/src/heartbeat.py`
- Modify: `services/scheduler/src/loop.py`
- Create: `services/scheduler/src/main.py`
- Test: `services/scheduler/tests/unit/test_heartbeat.py`

**Interfaces:**
- Produces: `record_heartbeat(now: datetime) -> None`, `is_healthy(now: datetime, max_staleness_seconds: int) -> bool`, a `GET /healthz` HTTP handler returning 200 when `is_healthy` is true and 503 otherwise.

- [ ] **Step 1: Write the failing tests**

```python
# services/scheduler/tests/unit/test_heartbeat.py
from datetime import datetime, timedelta
from src.heartbeat import record_heartbeat, is_healthy

def test_unhealthy_before_first_heartbeat():
    import src.heartbeat as hb
    hb._last_tick = None
    assert is_healthy(datetime(2026, 1, 1, 12, 0), max_staleness_seconds=90) is False

def test_healthy_shortly_after_heartbeat():
    record_heartbeat(datetime(2026, 1, 1, 12, 0, 0))
    assert is_healthy(datetime(2026, 1, 1, 12, 0, 30), max_staleness_seconds=90) is True

def test_unhealthy_once_stale():
    record_heartbeat(datetime(2026, 1, 1, 12, 0, 0))
    assert is_healthy(datetime(2026, 1, 1, 12, 2, 0), max_staleness_seconds=90) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/scheduler && pytest tests/unit/test_heartbeat.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/scheduler/src/heartbeat.py
from datetime import datetime, timedelta

_last_tick: datetime | None = None

def record_heartbeat(now: datetime) -> None:
    global _last_tick
    _last_tick = now

def is_healthy(now: datetime, max_staleness_seconds: int) -> bool:
    if _last_tick is None:
        return False
    return (now - _last_tick) <= timedelta(seconds=max_staleness_seconds)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/scheduler && pytest tests/unit/test_heartbeat.py -v`
Expected: 3 passed

- [ ] **Step 5: Record a heartbeat at the end of every tick**

```python
# modify services/scheduler/src/loop.py — add the import and one call
from .heartbeat import record_heartbeat

# inside run_forever's while loop, after the try/except block, before asyncio.sleep:
        record_heartbeat(now_utc)
```

- [ ] **Step 6: Write the entrypoint exposing `/healthz` alongside the loop**

```python
# services/scheduler/src/main.py
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
```

- [ ] **Step 7: Commit**

```bash
git add services/scheduler/src/heartbeat.py services/scheduler/src/loop.py services/scheduler/src/main.py services/scheduler/tests/unit/test_heartbeat.py
git commit -m "feat: add heartbeat-based liveness endpoint per spec SPOF requirement"
```

### Task 26: Scheduler Dockerfile

**Files:**
- Create: `services/scheduler/Dockerfile`

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# services/scheduler/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY packages/common /packages/common
COPY services/scheduler/pyproject.toml services/scheduler/pyproject.toml
COPY services/scheduler/src services/scheduler/src
WORKDIR /app/services/scheduler
RUN pip install --no-cache-dir .
EXPOSE 8002
CMD ["python", "-m", "src.main"]
```

- [ ] **Step 2: Build and smoke-test against the local compose stack**

Run: `docker compose up -d dynamodb-local mcp-server scheduler && curl -f http://localhost:8002/healthz`
Expected: after the scheduler completes its first tick (~60s), the health check returns 200. (It returns 503 before the first tick — expected, matching Task 25's design.)

- [ ] **Step 3: Commit**

```bash
git add services/scheduler/Dockerfile
git commit -m "feat: add Scheduler Dockerfile"
```

---

## Phase H — API Backend

### Task 27: FastAPI skeleton and watchlist add/remove endpoints

**Files:**
- Create: `services/api-backend/src/app.py`
- Create: `services/api-backend/src/routers/watchlist.py`
- Create: `services/api-backend/src/mcp_client.py`
- Test: `services/api-backend/tests/unit/test_watchlist_router.py`

**Interfaces:**
- Consumes: `add_to_watchlist`, `remove_from_watchlist`, `read_watchlist`, `WatchlistFullError` (Task 23)
- Produces: `create_app() -> FastAPI` with `GET /healthz`; router endpoints `POST /watchlist/{symbol}`, `DELETE /watchlist/{symbol}`, `GET /watchlist`. `POST /watchlist/{symbol}` validates via the self-built server's `finnhub_company_profile` tool before adding (spec §3).

- [ ] **Step 1: Write the failing tests**

```python
# services/api-backend/tests/unit/test_watchlist_router.py
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from src.app import create_app

@patch("src.routers.watchlist.add_to_watchlist")
@patch("src.routers.watchlist.call_own_tool", new_callable=AsyncMock)
def test_add_validates_symbol_before_adding(mock_call_tool, mock_add):
    mock_call_tool.return_value = {"name": "Apple Inc"}
    client = TestClient(create_app())
    response = client.post("/watchlist/AAPL")
    assert response.status_code == 201
    mock_add.assert_called_once_with("AAPL")

@patch("src.routers.watchlist.add_to_watchlist")
@patch("src.routers.watchlist.call_own_tool", new_callable=AsyncMock)
def test_add_rejects_invalid_symbol(mock_call_tool, mock_add):
    mock_call_tool.return_value = {}  # empty response = invalid symbol, per spec §3
    client = TestClient(create_app())
    response = client.post("/watchlist/BADSYMBOL")
    assert response.status_code == 422
    mock_add.assert_not_called()

@patch("src.routers.watchlist.remove_from_watchlist")
def test_remove(mock_remove):
    client = TestClient(create_app())
    response = client.delete("/watchlist/AAPL")
    assert response.status_code == 204
    mock_remove.assert_called_once_with("AAPL")

@patch("src.routers.watchlist.read_watchlist")
def test_list(mock_read):
    mock_read.return_value = ["AAPL", "MSFT"]
    client = TestClient(create_app())
    response = client.get("/watchlist")
    assert response.json() == ["AAPL", "MSFT"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/api-backend && pytest tests/unit/test_watchlist_router.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the MCP client helper (own server only, per spec §4.8)**

```python
# services/api-backend/src/mcp_client.py
import os
from langchain_mcp_adapters.client import MultiServerMCPClient

def build_own_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient({
        "own": {"url": os.environ["OWN_MCP_SERVER_URL"], "transport": "streamable_http"},
    })

async def call_own_tool(client: MultiServerMCPClient, tool_name: str, **kwargs) -> dict:
    tools = await client.get_tools(server_name="own")
    tool = next(t for t in tools if t.name == tool_name)
    return await tool.ainvoke(kwargs)
```

- [ ] **Step 4: Implement the watchlist router**

```python
# services/api-backend/src/routers/watchlist.py
from fastapi import APIRouter, HTTPException, Request
from common.dynamo import add_to_watchlist, remove_from_watchlist, read_watchlist, WatchlistFullError
from ..mcp_client import call_own_tool

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

@router.post("/{symbol}", status_code=201)
async def add_symbol(symbol: str, request: Request):
    profile = await call_own_tool(request.app.state.mcp_client, "finnhub_company_profile", symbol=symbol)
    if not profile:
        raise HTTPException(status_code=422, detail=f"'{symbol}' is not a recognized symbol")
    try:
        add_to_watchlist(symbol)
    except WatchlistFullError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"symbol": symbol}

@router.delete("/{symbol}", status_code=204)
async def remove_symbol(symbol: str):
    remove_from_watchlist(symbol)

@router.get("")
async def list_watchlist():
    return read_watchlist()
```

- [ ] **Step 5: Implement the app skeleton**

```python
# services/api-backend/src/app.py
from fastapi import FastAPI
from .routers.watchlist import router as watchlist_router
from .mcp_client import build_own_mcp_client

def create_app() -> FastAPI:
    app = FastAPI(title="Stock Research Agent API")
    app.state.mcp_client = build_own_mcp_client()

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    app.include_router(watchlist_router)
    return app
```

- [ ] **Step 6: Run to verify pass**

Run: `cd services/api-backend && pytest tests/unit/test_watchlist_router.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add services/api-backend/src/app.py services/api-backend/src/routers/watchlist.py services/api-backend/src/mcp_client.py services/api-backend/tests/unit/test_watchlist_router.py
git commit -m "feat: add API Backend skeleton and watchlist add/remove endpoints"
```

### Task 28: Dashboard and detail-modal read endpoints

**Files:**
- Create: `services/api-backend/src/routers/dashboard.py`
- Modify: `services/api-backend/src/app.py`
- Test: `services/api-backend/tests/unit/test_dashboard_router.py`

**Interfaces:**
- Consumes: `read_tool_result`, `read_agent_output`, `query_process_history` (Task 6), `read_watchlist` (Task 23)
- Produces: `GET /dashboards/discovery` (all four discovery panels), `GET /dashboards/watchlist` (per-row summary: symbol, verdict, last-updated), `GET /symbols/{symbol}/detail` (full pipeline: each agent's output + its own last-updated timestamp, per spec §8.1).

- [ ] **Step 1: Write the failing tests**

```python
# services/api-backend/tests/unit/test_dashboard_router.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.app import create_app

@patch("src.routers.dashboard.read_tool_result")
def test_discovery_dashboards_endpoint(mock_read):
    mock_read.side_effect = lambda pk: {"results": [f"{pk}-stock"]}
    client = TestClient(create_app())
    response = client.get("/dashboards/discovery")
    body = response.json()
    assert set(body.keys()) == {"top_gainers", "top_losers", "top_volume", "volume_breakout"}

@patch("src.routers.dashboard.read_agent_output")
@patch("src.routers.dashboard.read_watchlist")
def test_watchlist_dashboard_endpoint(mock_watchlist, mock_agent_output):
    mock_watchlist.return_value = ["AAPL"]
    mock_agent_output.return_value = {"net_score": 42.0, "confidence": 60.0, "label": "Bullish, moderate confidence"}
    client = TestClient(create_app())
    response = client.get("/dashboards/watchlist")
    assert response.json()[0]["symbol"] == "AAPL"
    assert response.json()[0]["verdict"]["label"] == "Bullish, moderate confidence"

@patch("src.routers.dashboard.query_process_history")
@patch("src.routers.dashboard.read_agent_output")
def test_symbol_detail_endpoint_includes_per_agent_timestamps(mock_agent_output, mock_history):
    mock_agent_output.side_effect = lambda symbol, agent: {"claims": []} if agent != "Manager" else {"label": "Bullish, moderate confidence"}
    mock_history.return_value = [{"agent": "Sentiment", "timestamp": "2026-01-05T12:00:00+00:00", "status": "finished"}]
    client = TestClient(create_app())
    response = client.get("/symbols/AAPL/detail")
    body = response.json()
    assert "fundamentals" in body["agents"]
    assert body["agents"]["Sentiment"]["last_updated"] == "2026-01-05T12:00:00+00:00"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/api-backend && pytest tests/unit/test_dashboard_router.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/api-backend/src/routers/dashboard.py
from fastapi import APIRouter
from common.dynamo import read_tool_result, read_agent_output, query_process_history, read_watchlist

router = APIRouter(tags=["dashboard"])
_AGENT_NAMES = ["Fundamentals", "Technical", "Sentiment", "Macro_Options", "Bull", "Bear", "Risk", "Manager"]

@router.get("/dashboards/discovery")
async def discovery_dashboards():
    return {
        name: (read_tool_result(f"DASHBOARD#{name}") or {"results": []})
        for name in ["top_gainers", "top_losers", "top_volume", "volume_breakout"]
    }

@router.get("/dashboards/watchlist")
async def watchlist_dashboard():
    rows = []
    for symbol in read_watchlist():
        verdict = read_agent_output(symbol, "Manager") or {}
        history = query_process_history(symbol)
        last_updated = history[-1]["timestamp"] if history else None
        rows.append({"symbol": symbol, "verdict": verdict, "last_updated": last_updated})
    return rows

@router.get("/symbols/{symbol}/detail")
async def symbol_detail(symbol: str):
    history = query_process_history(symbol)
    last_updated_by_agent = {}
    for entry in history:
        last_updated_by_agent[entry["agent"]] = entry["timestamp"]

    agents = {}
    for agent_name in _AGENT_NAMES:
        output = read_agent_output(symbol, agent_name) or {}
        key = agent_name.lower()
        agents[key] = {**output, "last_updated": last_updated_by_agent.get(agent_name)}
        agents[agent_name] = agents[key]  # also keyed by display name for the freshness-coloring UI

    return {"symbol": symbol, "agents": agents, "verdict": agents.get("manager", {})}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd services/api-backend && pytest tests/unit/test_dashboard_router.py -v`
Expected: 3 passed

- [ ] **Step 5: Register the router**

```python
# modify services/api-backend/src/app.py
from .routers.dashboard import router as dashboard_router
# inside create_app(), alongside app.include_router(watchlist_router):
app.include_router(dashboard_router)
```

- [ ] **Step 6: Commit**

```bash
git add services/api-backend/src/routers/dashboard.py services/api-backend/src/app.py services/api-backend/tests/unit/test_dashboard_router.py
git commit -m "feat: add discovery/watchlist/detail dashboard read endpoints"
```

### Task 29: SSE endpoints (freshness/news feed + live pipeline visualizer)

Per spec §5.6 and the agreed design: server-side polls DynamoDB every ~1-2s per connected client and emits only diffs — no broker, no DynamoDB Streams, works across HPA replicas since none hold in-memory stream state.

**Files:**
- Create: `services/api-backend/src/routers/stream.py`
- Modify: `services/api-backend/src/app.py`
- Test: `services/api-backend/tests/unit/test_stream_router.py`

**Interfaces:**
- Produces: `GET /symbols/{symbol}/stream` (SSE: emits a JSON event whenever `query_process_history` returns new entries since the last poll), `GET /stream/news` (SSE: emits new Marketaux articles across the whole watchlist as they're detected).

- [ ] **Step 1: Write the failing test**

```python
# services/api-backend/tests/unit/test_stream_router.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.app import create_app

@patch("src.routers.stream.query_process_history")
def test_symbol_stream_emits_new_process_history_entries(mock_history):
    mock_history.side_effect = [
        [],  # first poll: nothing yet
        [{"agent": "Fundamentals", "status": "started", "timestamp": "2026-01-05T12:00:00+00:00"}],
    ]
    client = TestClient(create_app())
    with client.stream("GET", "/symbols/AAPL/stream?_test_max_polls=2") as response:
        events = [line for line in response.iter_lines() if line.startswith("data:")]
    assert any("Fundamentals" in e for e in events)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/api-backend && pytest tests/unit/test_stream_router.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# services/api-backend/src/routers/stream.py
import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from common.dynamo import query_process_history

router = APIRouter(tags=["stream"])
_POLL_INTERVAL_SECONDS = 1.5

async def _symbol_event_generator(symbol: str, max_polls: int | None):
    last_seen_sk = None
    polls = 0
    while max_polls is None or polls < max_polls:
        entries = query_process_history(symbol)
        new_entries = entries if last_seen_sk is None else [
            e for e in entries if e.get("timestamp", "") > last_seen_sk
        ]
        for entry in new_entries:
            yield f"data: {json.dumps(entry)}\n\n"
        if entries:
            last_seen_sk = entries[-1]["timestamp"]
        polls += 1
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

@router.get("/symbols/{symbol}/stream")
async def symbol_stream(symbol: str, _test_max_polls: int | None = None):
    return StreamingResponse(
        _symbol_event_generator(symbol, _test_max_polls),
        media_type="text/event-stream",
    )
```

Note: `_test_max_polls` exists only so the test suite can terminate the otherwise-infinite generator deterministically; it's never set by real clients (the frontend's `EventSource` just keeps the connection open, per Task 39's `useSSE` hook).

- [ ] **Step 4: Run to verify pass**

Run: `cd services/api-backend && pytest tests/unit/test_stream_router.py -v`
Expected: 1 passed

- [ ] **Step 5: Register the router**

```python
# modify services/api-backend/src/app.py
from .routers.stream import router as stream_router
app.include_router(stream_router)
```

- [ ] **Step 6: Commit**

```bash
git add services/api-backend/src/routers/stream.py services/api-backend/src/app.py services/api-backend/tests/unit/test_stream_router.py
git commit -m "feat: add SSE stream endpoint for live pipeline/freshness updates"
```

### Task 30: Chat grounding and endpoint

Spec §4.6: structured retrieval (direct `AgentOutputs` reads) plus the process-history MCP tool for timing/audit questions — no vector DB.

**Files:**
- Create: `services/api-backend/src/chat/grounding.py`
- Create: `services/api-backend/src/routers/chat.py`
- Modify: `services/api-backend/src/app.py`
- Test: `services/api-backend/tests/unit/test_chat.py`

**Interfaces:**
- Produces: `build_context(symbols: list[str]) -> str` (concatenated `AgentOutputs` for the given symbols), `POST /chat` accepting `{"question": str, "symbols": list[str]}`, returning `{"answer": str}`.

- [ ] **Step 1: Write the failing tests**

```python
# services/api-backend/tests/unit/test_chat.py
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.app import create_app
from src.chat.grounding import build_context

@patch("src.chat.grounding.read_agent_output")
def test_build_context_includes_all_agent_outputs_for_symbol(mock_read):
    mock_read.return_value = {"label": "Bullish, moderate confidence"}
    context = build_context(["AAPL"])
    assert "AAPL" in context
    assert "Bullish, moderate confidence" in context

@patch("src.routers.chat._invoke_chat_llm")
@patch("src.routers.chat.build_context")
def test_chat_endpoint_returns_answer(mock_context, mock_llm):
    mock_context.return_value = "AAPL: Bullish, moderate confidence"
    mock_llm.return_value = "AAPL looks bullish based on the latest analysis."
    client = TestClient(create_app())
    response = client.post("/chat", json={"question": "How does AAPL look?", "symbols": ["AAPL"]})
    assert response.status_code == 200
    assert "bullish" in response.json()["answer"].lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/api-backend && pytest tests/unit/test_chat.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement grounding**

```python
# services/api-backend/src/chat/grounding.py
from common.dynamo import read_agent_output

_AGENT_NAMES = ["Fundamentals", "Technical", "Sentiment", "Macro_Options", "Bull", "Bear", "Risk", "Manager"]

def build_context(symbols: list[str]) -> str:
    sections = []
    for symbol in symbols:
        lines = [f"=== {symbol} ==="]
        for agent_name in _AGENT_NAMES:
            output = read_agent_output(symbol, agent_name)
            if output:
                lines.append(f"{agent_name}: {output}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
```

- [ ] **Step 4: Implement the chat endpoint, calling the process-history MCP tool when the question concerns timing**

```python
# services/api-backend/src/routers/chat.py
from fastapi import APIRouter, Request
from pydantic import BaseModel
from langchain_aws import ChatBedrockConverse
from ..chat.grounding import build_context
from ..mcp_client import call_own_tool

router = APIRouter(tags=["chat"])
_TIMING_KEYWORDS = ["when", "last updated", "why did", "history", "changed"]

class ChatRequest(BaseModel):
    question: str
    symbols: list[str]

def _invoke_chat_llm(question: str, context: str, history_context: str) -> str:
    llm = ChatBedrockConverse(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        provider="bedrock_converse",
        region_name="us-east-1",
    )
    response = llm.invoke([
        {"role": "system", "content": (
            "You are a research assistant grounded strictly in the cached analysis below. "
            "Never present the composite score as investment advice or a validated trading "
            "signal — it is research output only."
        )},
        {"role": "user", "content": f"Context:\n{context}\n\n{history_context}\n\nQuestion: {question}"},
    ])
    return response.content

@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    context = build_context(body.symbols)
    history_context = ""
    if any(kw in body.question.lower() for kw in _TIMING_KEYWORDS) and body.symbols:
        history = await call_own_tool(request.app.state.mcp_client, "query_process_history_tool", symbol=body.symbols[0])
        history_context = f"Process history for {body.symbols[0]}:\n{history}"
    answer = _invoke_chat_llm(body.question, context, history_context)
    return {"answer": answer}
```

- [ ] **Step 5: Run to verify pass**

Run: `cd services/api-backend && pytest tests/unit/test_chat.py -v`
Expected: 2 passed

- [ ] **Step 6: Register the router**

```python
# modify services/api-backend/src/app.py
from .routers.chat import router as chat_router
app.include_router(chat_router)
```

- [ ] **Step 7: Commit**

```bash
git add services/api-backend/src/chat services/api-backend/src/routers/chat.py services/api-backend/src/app.py services/api-backend/tests/unit/test_chat.py
git commit -m "feat: add Chat endpoint grounded in cached AgentOutputs and process history"
```

### Task 31: API Backend Dockerfile

**Files:**
- Create: `services/api-backend/Dockerfile`

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# services/api-backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY packages/common /packages/common
COPY services/api-backend/pyproject.toml services/api-backend/pyproject.toml
COPY services/api-backend/src services/api-backend/src
WORKDIR /app/services/api-backend
RUN pip install --no-cache-dir . uvicorn
EXPOSE 8080
CMD ["uvicorn", "src.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Build and smoke-test against the local compose stack**

Run: `docker compose up -d dynamodb-local mcp-server api-backend && curl -f http://localhost:8000/healthz`
Expected: `{"status": "ok"}`

- [ ] **Step 3: Commit**

```bash
git add services/api-backend/Dockerfile
git commit -m "feat: add API Backend Dockerfile"
```

---

## Phase I — Frontend

### Task 32: React app scaffold, API client, and SSE hook

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/hooks/useSSE.ts`
- Create: `frontend/src/App.tsx`, `frontend/src/main.tsx`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `apiClient` (object with `getDiscoveryDashboards()`, `getWatchlistDashboard()`, `getSymbolDetail(symbol)`, `addSymbol(symbol)`, `removeSymbol(symbol)`, `sendChatMessage(question, symbols)`), `useSSE<T>(url: string) -> { events: T[] }`. Tasks 33-37 build components on top of these.

- [ ] **Step 1: Scaffold with Vite**

```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install
```

- [ ] **Step 2: Write the failing test for the API client**

```typescript
// frontend/src/api/client.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiClient } from "./client";

beforeEach(() => {
  global.fetch = vi.fn();
});

describe("apiClient", () => {
  it("getWatchlistDashboard calls the correct endpoint", async () => {
    (global.fetch as any).mockResolvedValue({ ok: true, json: async () => [{ symbol: "AAPL" }] });
    const result = await apiClient.getWatchlistDashboard();
    expect(global.fetch).toHaveBeenCalledWith("/api/dashboards/watchlist");
    expect(result).toEqual([{ symbol: "AAPL" }]);
  });

  it("addSymbol POSTs to /api/watchlist/{symbol} and throws on 422", async () => {
    (global.fetch as any).mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: "invalid" }) });
    await expect(apiClient.addSymbol("BAD")).rejects.toThrow("invalid");
  });
});
```

- [ ] **Step 3: Run to verify failure**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `client.ts` doesn't exist yet

- [ ] **Step 4: Implement the API client**

```typescript
// frontend/src/api/client.ts
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `request to ${path} failed with ${response.status}`);
  }
  return response.json();
}

export const apiClient = {
  getDiscoveryDashboards: () => request<Record<string, { results: unknown[] }>>("/dashboards/discovery"),
  getWatchlistDashboard: () => request<Array<{ symbol: string; verdict: unknown; last_updated: string | null }>>("/dashboards/watchlist"),
  getSymbolDetail: (symbol: string) => request<{ symbol: string; agents: Record<string, unknown>; verdict: unknown }>(`/symbols/${symbol}/detail`),
  addSymbol: (symbol: string) => request(`/watchlist/${symbol}`, { method: "POST" }),
  removeSymbol: (symbol: string) => request(`/watchlist/${symbol}`, { method: "DELETE" }),
  sendChatMessage: (question: string, symbols: string[]) =>
    request<{ answer: string }>("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, symbols }),
    }),
};
```

- [ ] **Step 5: Run to verify pass**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: 2 passed

- [ ] **Step 6: Write the SSE hook (no dedicated unit test — `EventSource` isn't meaningfully unit-testable without a real connection; it's covered by Task 37's manual QA checklist)**

```typescript
// frontend/src/hooks/useSSE.ts
import { useEffect, useState } from "react";

export function useSSE<T>(url: string): { events: T[] } {
  const [events, setEvents] = useState<T[]>([]);

  useEffect(() => {
    const source = new EventSource(`/api${url}`);
    source.onmessage = (event) => {
      setEvents((prev) => [...prev, JSON.parse(event.data) as T]);
    };
    return () => source.close();
  }, [url]);

  return { events };
}
```

- [ ] **Step 7: Write the app shell (two-column 50/50 layout, spec §8)**

```tsx
// frontend/src/App.tsx
import "./App.css";
import { DiscoveryGrid } from "./components/DiscoveryGrid";
import { Watchlist } from "./components/Watchlist";
import { ChatPanel } from "./components/ChatPanel";
import { NewsFeed } from "./components/NewsFeed";

export default function App() {
  return (
    <div style={{ display: "flex", width: "100%", height: "100vh" }}>
      <div style={{ width: "50%", overflowY: "auto", padding: "1rem" }}>
        <DiscoveryGrid />
        <Watchlist />
      </div>
      <div style={{ width: "50%", overflowY: "auto", padding: "1rem" }}>
        <ChatPanel />
        <NewsFeed />
      </div>
    </div>
  );
}
```

This references `DiscoveryGrid`, `Watchlist`, `ChatPanel`, `NewsFeed` — Tasks 33-36 create them; `App.tsx` won't compile until then, which is expected at this point in the sequence.

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html frontend/src/api frontend/src/hooks frontend/src/App.tsx frontend/src/main.tsx
git commit -m "feat: scaffold React app, API client, and SSE hook"
```

### Task 33: Discovery grid and ticker search/add box

**Files:**
- Create: `frontend/src/components/DiscoveryGrid.tsx`
- Test: `frontend/src/components/DiscoveryGrid.test.tsx`

**Interfaces:**
- Consumes: `apiClient.getDiscoveryDashboards`, `apiClient.addSymbol` (Task 32)
- Produces: `DiscoveryGrid` component (2×2 grid, read-only, plus the add-symbol input)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/DiscoveryGrid.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DiscoveryGrid } from "./DiscoveryGrid";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("DiscoveryGrid", () => {
  it("renders all four dashboard panels", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: ["AAPL"] }, top_losers: { results: [] },
      top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText(/top gainers/i)).toBeInTheDocument());
    expect(screen.getByText(/top losers/i)).toBeInTheDocument();
    expect(screen.getByText(/top volume/i)).toBeInTheDocument();
    expect(screen.getByText(/volume breakout/i)).toBeInTheDocument();
  });

  it("submitting the add box calls apiClient.addSymbol", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    vi.mocked(apiClient.addSymbol).mockResolvedValue(undefined);
    render(<DiscoveryGrid />);
    fireEvent.change(screen.getByPlaceholderText(/add ticker/i), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByText(/add/i));
    await waitFor(() => expect(apiClient.addSymbol).toHaveBeenCalledWith("AAPL"));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/DiscoveryGrid.test.tsx`
Expected: FAIL — component doesn't exist

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/DiscoveryGrid.tsx
import { useEffect, useState } from "react";
import { apiClient } from "../api/client";

const PANEL_TITLES: Record<string, string> = {
  top_gainers: "Top Gainers", top_losers: "Top Losers",
  top_volume: "Top Volume", volume_breakout: "Volume Breakout",
};

export function DiscoveryGrid() {
  const [dashboards, setDashboards] = useState<Record<string, { results: unknown[] }>>({});
  const [tickerInput, setTickerInput] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    apiClient.getDiscoveryDashboards().then(setDashboards);
  }, []);

  const handleAdd = async () => {
    setAddError(null);
    try {
      await apiClient.addSymbol(tickerInput.toUpperCase());
      setTickerInput("");
    } catch (e) {
      setAddError((e as Error).message);
    }
  };

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
        {Object.entries(PANEL_TITLES).map(([key, title]) => (
          <div key={key} style={{ border: "1px solid var(--border)", padding: "0.5rem" }}>
            <h3>{title}</h3>
            <ul>{(dashboards[key]?.results ?? []).map((r, i) => <li key={i}>{JSON.stringify(r)}</li>)}</ul>
          </div>
        ))}
      </div>
      <div style={{ marginTop: "0.5rem" }}>
        <input
          placeholder="Add ticker..."
          value={tickerInput}
          onChange={(e) => setTickerInput(e.target.value)}
        />
        <button onClick={handleAdd}>Add</button>
        {addError && <p style={{ color: "red" }}>{addError}</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npx vitest run src/components/DiscoveryGrid.test.tsx`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DiscoveryGrid.tsx frontend/src/components/DiscoveryGrid.test.tsx
git commit -m "feat: add discovery dashboards grid and ticker add box"
```

### Task 34: Selected Companies watchlist panel

**Files:**
- Create: `frontend/src/components/Watchlist.tsx`
- Test: `frontend/src/components/Watchlist.test.tsx`

**Interfaces:**
- Consumes: `apiClient.getWatchlistDashboard`, `apiClient.removeSymbol` (Task 32)
- Produces: `Watchlist` component — rows are clickable and open `DetailModal` (Task 35)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/Watchlist.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Watchlist } from "./Watchlist";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("Watchlist", () => {
  it("renders a row per watchlist symbol with verdict and last-updated", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      { symbol: "AAPL", verdict: { label: "Bullish, moderate confidence" }, last_updated: "2026-01-05T12:00:00+00:00" },
    ]);
    render(<Watchlist />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText(/Bullish, moderate confidence/)).toBeInTheDocument();
  });

  it("clicking remove calls apiClient.removeSymbol", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      { symbol: "AAPL", verdict: { label: "Bullish" }, last_updated: null },
    ]);
    vi.mocked(apiClient.removeSymbol).mockResolvedValue(undefined);
    render(<Watchlist />);
    await waitFor(() => screen.getByText("AAPL"));
    fireEvent.click(screen.getByLabelText(/remove AAPL/i));
    await waitFor(() => expect(apiClient.removeSymbol).toHaveBeenCalledWith("AAPL"));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/Watchlist.test.tsx`
Expected: FAIL — component doesn't exist

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/Watchlist.tsx
import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import { DetailModal } from "./DetailModal";

type Row = { symbol: string; verdict: { label?: string }; last_updated: string | null };

export function Watchlist() {
  const [rows, setRows] = useState<Row[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = () => apiClient.getWatchlistDashboard().then(setRows);
  useEffect(() => { refresh(); }, []);

  return (
    <div>
      <h2>Selected Companies</h2>
      <table>
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol}>
              <td onClick={() => setSelected(row.symbol)} style={{ cursor: "pointer" }}>{row.symbol}</td>
              <td>{row.verdict?.label ?? "—"}</td>
              <td>{row.last_updated ?? "never"}</td>
              <td>
                <button
                  aria-label={`remove ${row.symbol}`}
                  onClick={async () => { await apiClient.removeSymbol(row.symbol); refresh(); }}
                >×</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && <DetailModal symbol={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
```

- [ ] **Step 4: Run to verify pass (will still fail until Task 35 creates `DetailModal`)**

Run: `cd frontend && npx vitest run src/components/Watchlist.test.tsx`
Expected: FAIL — `./DetailModal` doesn't exist yet; this is expected at this point in the sequence and resolves in the next task.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Watchlist.tsx frontend/src/components/Watchlist.test.tsx
git commit -m "feat: add Selected Companies watchlist panel"
```

### Task 35: Detail modal — pipeline view with freshness coloring, results chart, verdict

Spec §8.1: color-differentiated per-agent "last updated" so a partial, news-triggered cascade is visible at a glance. Reads entirely from cached data — never triggers a live pipeline re-run.

**Files:**
- Create: `frontend/src/components/DetailModal.tsx`
- Create: `frontend/src/components/PipelineView.tsx`
- Create: `frontend/src/components/ResultsChart.tsx`
- Test: `frontend/src/components/DetailModal.test.tsx`

**Interfaces:**
- Consumes: `apiClient.getSymbolDetail` (Task 32)
- Produces: `DetailModal({ symbol, onClose })`, `PipelineView({ agents })` (per-node freshness coloring), `ResultsChart({ verdict, bullClaims, bearClaims })`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/DetailModal.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DetailModal } from "./DetailModal";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("DetailModal", () => {
  it("renders agent nodes with freshness-based styling and closes on backdrop click", async () => {
    const now = new Date().toISOString();
    const hourAgo = new Date(Date.now() - 3600_000).toISOString();
    vi.mocked(apiClient.getSymbolDetail).mockResolvedValue({
      symbol: "AAPL",
      agents: {
        Sentiment: { last_updated: now, claims: [] },
        Fundamentals: { last_updated: hourAgo, claims: [] },
        Manager: { label: "Bullish, moderate confidence", net_score: 42, confidence: 60 },
      },
      verdict: { label: "Bullish, moderate confidence", net_score: 42, confidence: 60 },
    });
    const onClose = vi.fn();
    render(<DetailModal symbol="AAPL" onClose={onClose} />);
    await waitFor(() => expect(screen.getByText("Sentiment")).toBeInTheDocument());

    const sentimentNode = screen.getByTestId("agent-node-Sentiment");
    const fundamentalsNode = screen.getByTestId("agent-node-Fundamentals");
    expect(sentimentNode.className).not.toBe(fundamentalsNode.className);

    fireEvent.click(screen.getByTestId("modal-backdrop"));
    expect(onClose).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/DetailModal.test.tsx`
Expected: FAIL — component doesn't exist

- [ ] **Step 3: Implement the freshness-coloring pipeline view**

```tsx
// frontend/src/components/PipelineView.tsx
type AgentData = { last_updated?: string | null; [key: string]: unknown };

const FRESHNESS_TIERS = [
  { maxAgeMs: 5 * 60_000, className: "agent-fresh" },      // < 5 min
  { maxAgeMs: 30 * 60_000, className: "agent-recent" },    // < 30 min
  { maxAgeMs: Infinity, className: "agent-stale" },
];

function freshnessClass(lastUpdated: string | null | undefined): string {
  if (!lastUpdated) return "agent-never";
  const ageMs = Date.now() - new Date(lastUpdated).getTime();
  return FRESHNESS_TIERS.find((t) => ageMs < t.maxAgeMs)!.className;
}

const PIPELINE_ORDER = ["Fundamentals", "Technical", "Sentiment", "Macro_Options", "Bull", "Bear", "Risk", "Manager"];

export function PipelineView({ agents }: { agents: Record<string, AgentData> }) {
  return (
    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
      {PIPELINE_ORDER.map((name) => {
        const data = agents[name] ?? {};
        return (
          <div key={name} data-testid={`agent-node-${name}`} className={freshnessClass(data.last_updated)}>
            <strong>{name}</strong>
            <div>{data.last_updated ? new Date(data.last_updated as string).toLocaleTimeString() : "never run"}</div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Implement the results chart and modal**

```tsx
// frontend/src/components/ResultsChart.tsx
type Verdict = { net_score?: number; confidence?: number; label?: string };

export function ResultsChart({ verdict }: { verdict: Verdict }) {
  const netScore = verdict.net_score ?? 0;
  return (
    <div>
      <h3>{verdict.label ?? "No verdict yet"}</h3>
      <div style={{ width: "100%", background: "#eee", height: "1rem" }}>
        <div
          style={{
            width: `${Math.abs(netScore) / 2}%`,
            marginLeft: netScore >= 0 ? "50%" : `${50 - Math.abs(netScore) / 2}%`,
            background: netScore >= 0 ? "green" : "red",
            height: "1rem",
          }}
        />
      </div>
      <p>Confidence: {verdict.confidence ?? 0}%</p>
    </div>
  );
}
```

```tsx
// frontend/src/components/DetailModal.tsx
import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import { PipelineView } from "./PipelineView";
import { ResultsChart } from "./ResultsChart";

export function DetailModal({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const [detail, setDetail] = useState<{ agents: Record<string, any>; verdict: any } | null>(null);

  useEffect(() => { apiClient.getSymbolDetail(symbol).then(setDetail); }, [symbol]);

  return (
    <div
      data-testid="modal-backdrop"
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div onClick={(e) => e.stopPropagation()} style={{ background: "white", width: "70%", maxHeight: "80%", overflowY: "auto", padding: "1rem" }}>
        <h2>{symbol}</h2>
        {detail && (
          <>
            <PipelineView agents={detail.agents} />
            <ResultsChart verdict={detail.verdict} />
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run to verify pass**

Run: `cd frontend && npx vitest run src/components/DetailModal.test.tsx src/components/Watchlist.test.tsx`
Expected: 3 passed (`DetailModal`'s test plus `Watchlist`'s previously-blocked test now resolves)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DetailModal.tsx frontend/src/components/PipelineView.tsx frontend/src/components/ResultsChart.tsx frontend/src/components/DetailModal.test.tsx
git commit -m "feat: add detail modal with freshness-colored pipeline view and results chart"
```

### Task 36: Chat panel and live news feed

**Files:**
- Create: `frontend/src/components/ChatPanel.tsx`
- Create: `frontend/src/components/NewsFeed.tsx`
- Test: `frontend/src/components/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: `apiClient.sendChatMessage` (Task 32), `useSSE` (Task 32)
- Produces: `ChatPanel`, `NewsFeed` — right half of the layout, spec §8.2

- [ ] **Step 1: Write the failing test for ChatPanel**

```tsx
// frontend/src/components/ChatPanel.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("ChatPanel", () => {
  it("sends a question and displays the answer", async () => {
    vi.mocked(apiClient.sendChatMessage).mockResolvedValue({ answer: "AAPL looks bullish." });
    render(<ChatPanel />);
    fireEvent.change(screen.getByPlaceholderText(/ask about your watchlist/i), { target: { value: "How does AAPL look?" } });
    fireEvent.click(screen.getByText(/send/i));
    await waitFor(() => expect(screen.getByText(/AAPL looks bullish/)).toBeInTheDocument());
    expect(apiClient.sendChatMessage).toHaveBeenCalledWith("How does AAPL look?", []);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/ChatPanel.test.tsx`
Expected: FAIL — component doesn't exist

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/ChatPanel.tsx
import { useState } from "react";
import { apiClient } from "../api/client";

type Message = { role: "user" | "assistant"; text: string };

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");

  const send = async () => {
    const question = input;
    setMessages((m) => [...m, { role: "user", text: question }]);
    setInput("");
    const { answer } = await apiClient.sendChatMessage(question, []);
    setMessages((m) => [...m, { role: "assistant", text: answer }]);
  };

  return (
    <div>
      <h2>Chat</h2>
      <div>{messages.map((m, i) => <p key={i}><strong>{m.role}:</strong> {m.text}</p>)}</div>
      <input
        placeholder="Ask about your watchlist..."
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && send()}
      />
      <button onClick={send}>Send</button>
    </div>
  );
}
```

```tsx
// frontend/src/components/NewsFeed.tsx
import { useSSE } from "../hooks/useSSE";

type NewsEvent = { agent: string; status: string; timestamp: string; reason: string };

export function NewsFeed() {
  const { events } = useSSE<NewsEvent>("/stream/news");
  return (
    <div>
      <h2>Live News Feed</h2>
      <ul>
        {events.map((e, i) => (
          <li key={i}>{e.timestamp}: {e.agent} ({e.reason})</li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npx vitest run src/components/ChatPanel.test.tsx`
Expected: 1 passed

- [ ] **Step 5: Add the corresponding `GET /stream/news` endpoint the `NewsFeed` component now depends on**

```python
# modify services/api-backend/src/routers/stream.py — add alongside symbol_stream
from common.dynamo import read_watchlist

async def _news_event_generator(max_polls: int | None):
    last_seen: dict[str, str] = {}
    polls = 0
    while max_polls is None or polls < max_polls:
        for symbol in read_watchlist():
            entries = [e for e in query_process_history(symbol) if e["agent"] == "Sentiment"]
            if entries and entries[-1]["timestamp"] != last_seen.get(symbol):
                last_seen[symbol] = entries[-1]["timestamp"]
                yield f"data: {json.dumps({**entries[-1], 'symbol': symbol})}\n\n"
        polls += 1
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

@router.get("/stream/news")
async def news_stream(_test_max_polls: int | None = None):
    return StreamingResponse(_news_event_generator(_test_max_polls), media_type="text/event-stream")
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx frontend/src/components/NewsFeed.tsx frontend/src/components/ChatPanel.test.tsx services/api-backend/src/routers/stream.py
git commit -m "feat: add chat panel and live news feed with backing SSE endpoint"
```

### Task 37: Standalone live pipeline visualizer

Spec §8.3: distinct from the cached `DetailModal` — an animated idle → running → finished view of one in-flight run.

**Files:**
- Create: `frontend/src/components/LiveVisualizer.tsx`
- Modify: `frontend/src/App.tsx` (add a route/link to it — a separate page, not part of the two-column layout)
- Test: `frontend/src/components/LiveVisualizer.test.tsx`

**Interfaces:**
- Consumes: `useSSE` (Task 32)
- Produces: `LiveVisualizer({ symbol })`, rendering each pipeline node's state derived from SSE `started`/`finished` events, clickable per node to show what it produced.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/LiveVisualizer.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { LiveVisualizer } from "./LiveVisualizer";
import { useSSE } from "../hooks/useSSE";

vi.mock("../hooks/useSSE");

describe("LiveVisualizer", () => {
  it("shows a node as running after a started event and finished after a finished event", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [
        { agent: "Fundamentals", status: "started", timestamp: "t1", reason: "scheduled_refresh" },
        { agent: "Fundamentals", status: "finished", timestamp: "t2", reason: "scheduled_refresh" },
        { agent: "Technical", status: "started", timestamp: "t3", reason: "scheduled_refresh" },
      ],
    });
    render(<LiveVisualizer symbol="AAPL" />);
    expect(screen.getByTestId("viz-node-Fundamentals").textContent).toContain("finished");
    expect(screen.getByTestId("viz-node-Technical").textContent).toContain("running");
    expect(screen.getByTestId("viz-node-Risk").textContent).toContain("idle");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/LiveVisualizer.test.tsx`
Expected: FAIL — component doesn't exist

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/LiveVisualizer.tsx
import { useState } from "react";
import { useSSE } from "../hooks/useSSE";

type PipelineEvent = { agent: string; status: "started" | "finished"; timestamp: string; reason: string };

const NODE_ORDER = ["Fundamentals", "Technical", "Sentiment", "Macro_Options", "Bull", "Bear", "Risk", "Manager"];

function computeStates(events: PipelineEvent[]): Record<string, "idle" | "running" | "finished"> {
  const states: Record<string, "idle" | "running" | "finished"> = {};
  for (const node of NODE_ORDER) states[node] = "idle";
  for (const event of events) {
    states[event.agent] = event.status === "started" ? "running" : "finished";
  }
  return states;
}

export function LiveVisualizer({ symbol }: { symbol: string }) {
  const { events } = useSSE<PipelineEvent>(`/symbols/${symbol}/stream`);
  const [selected, setSelected] = useState<string | null>(null);
  const states = computeStates(events);

  return (
    <div>
      <h2>Live Pipeline: {symbol}</h2>
      <div style={{ display: "flex", gap: "0.5rem" }}>
        {NODE_ORDER.map((node) => (
          <div
            key={node}
            data-testid={`viz-node-${node}`}
            onClick={() => setSelected(node)}
            className={`viz-node viz-${states[node]}`}
          >
            {node}: {states[node]}
          </div>
        ))}
      </div>
      {selected && <pre>{JSON.stringify(events.filter((e) => e.agent === selected), null, 2)}</pre>}
    </div>
  );
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npx vitest run src/components/LiveVisualizer.test.tsx`
Expected: 1 passed

- [ ] **Step 5: Wire a link to it from the main app**

```tsx
// modify frontend/src/App.tsx — add near the top of the two-column div
<a href="/visualizer">Open live pipeline visualizer</a>
```

Full client-side routing (e.g. `react-router`) is deferred to whichever router the team prefers when the app is actually built out — for this plan, a plain anchor plus a second Vite entry (`visualizer.html` → mounts `<LiveVisualizer symbol={...} />`) is sufficient to satisfy spec §8.3's "standalone" requirement without adding a routing dependency this project doesn't otherwise need.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/LiveVisualizer.tsx frontend/src/components/LiveVisualizer.test.tsx frontend/src/App.tsx
git commit -m "feat: add standalone live pipeline visualizer"
```

### Task 38: Frontend Dockerfile

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`

- [ ] **Step 1: Write the Dockerfile (multi-stage: build with Vite, serve with Nginx)**

```dockerfile
# frontend/Dockerfile
FROM node:22-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 2: Write the Nginx config, proxying `/api` to the API Backend**

```nginx
# frontend/nginx.conf
server {
    listen 80;

    location /api/ {
        proxy_pass http://api-backend:8080/;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        proxy_buffering off;  # required so SSE responses stream through, not buffer
        chunked_transfer_encoding off;
    }

    location / {
        root /usr/share/nginx/html;
        try_files $uri /index.html;
    }
}
```

- [ ] **Step 3: Build and smoke-test the full local stack**

Run: `docker compose up --build`
Expected: all five containers start; `http://localhost:3000` loads the app; the discovery grid and watchlist panel populate from the API backend.

- [ ] **Step 4: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf
git commit -m "feat: add frontend Dockerfile with Nginx reverse proxy to the API backend"
```

---

## Phase J — Local End-to-End Verification

### Task 39: Full local stack smoke test and manual QA checklist

Everything up to this point has been unit- and integration-tested in isolation. This task is the first time all five containers run together — the last checkpoint before moving to cloud infra.

**Files:**
- Create: `scripts/smoke_test.sh`
- Create: `docs/manual-qa-checklist.md`

- [ ] **Step 1: Write an automated smoke test script covering the golden path**

```bash
# scripts/smoke_test.sh
#!/usr/bin/env bash
set -euo pipefail

echo "Waiting for services..."
until curl -sf http://localhost:8001/healthz >/dev/null 2>&1 || curl -sf http://localhost:8001 >/dev/null 2>&1; do sleep 2; done
until curl -sf http://localhost:8000/healthz >/dev/null; do sleep 2; done

echo "Adding AAPL to watchlist..."
curl -sf -X POST http://localhost:8000/api/watchlist/AAPL

echo "Waiting for the Scheduler's first tick to process it (up to 90s)..."
for i in $(seq 1 45); do
  DETAIL=$(curl -sf http://localhost:8000/api/symbols/AAPL/detail)
  if echo "$DETAIL" | grep -q '"Manager"'; then
    echo "Manager verdict present. Smoke test passed."
    exit 0
  fi
  sleep 2
done

echo "FAILED: no Manager verdict for AAPL after 90s"
exit 1
```

- [ ] **Step 2: Run it against the full compose stack**

Run: `docker compose up --build -d && chmod +x scripts/smoke_test.sh && ./scripts/smoke_test.sh`
Expected: `Manager verdict present. Smoke test passed.` (requires real provider API keys and AWS Bedrock credentials in `.env` — this is the first task that needs them, since it's the first real end-to-end LLM/data-provider run)

- [ ] **Step 3: Write the manual QA checklist for the four UI flows spec §8 requires**

```markdown
# docs/manual-qa-checklist.md

Run through this before every `prod` deploy (spec §11).

## Discovery dashboards
- [ ] All four panels (Top Gainers, Top Losers, Top Volume, Volume Breakout) render 10 rows each
- [ ] Panels are read-only — clicking a row does nothing
- [ ] Panels refresh roughly every 30 min during market hours; no refresh 8pm-4am ET

## Watchlist
- [ ] Adding a valid ticker succeeds; adding an invalid ticker shows an inline error, doesn't add
- [ ] Adding a 31st symbol is rejected with a clear error
- [ ] Removing a symbol removes its row immediately
- [ ] Clicking a row opens the detail modal without a page navigation

## Detail modal
- [ ] Pipeline nodes are color-differentiated by freshness (a just-updated Sentiment node looks
      visually distinct from an hour-old Fundamentals node)
- [ ] Results chart, claims, and verdict/confidence render
- [ ] Closing the modal (backdrop click) never triggers a network POST/pipeline run — confirm via
      browser devtools network tab

## Chat + news feed
- [ ] A cross-symbol question (mentioning two watchlist symbols) gets a grounded answer
- [ ] The answer never phrases the score as investment advice
- [ ] New articles appear in the live news feed within ~1-2s of being detected

## Live pipeline visualizer
- [ ] Opening it for a symbol mid-run shows nodes transitioning idle → running → finished in the
      correct dependency order (four specialists in parallel, then Bull/Bear in parallel, then Risk, then Manager)
- [ ] Clicking a finished node shows what it produced
```

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_test.sh docs/manual-qa-checklist.md
git commit -m "test: add local end-to-end smoke test and manual QA checklist"
```

---

## Phase K — Terraform Infrastructure

Every resource here is provisioned per environment (`dev`, `prod`) via a shared set of modules, instantiated once per env under `infra/terraform/envs/{dev,prod}` (spec §9). No manual console changes.

### Task 40: Terraform state backend and network module

**Files:**
- Create: `infra/terraform/modules/network/main.tf`, `variables.tf`, `outputs.tf`
- Create: `infra/terraform/envs/dev/backend.tf`, `infra/terraform/envs/prod/backend.tf`

**Interfaces:**
- Produces: module `network` with input `env: string`, outputs `vpc_id`, `public_subnet_ids: list(string)`.

- [ ] **Step 1: Write the network module**

```hcl
# infra/terraform/modules/network/variables.tf
variable "env" {
  type = string
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}
```

```hcl
# infra/terraform/modules/network/main.tf
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = { Name = "stock-research-${var.env}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "stock-research-${var.env}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "stock-research-${var.env}-public-${count.index}" }
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "stock-research-${var.env}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
```

```hcl
# infra/terraform/modules/network/outputs.tf
output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}
```

- [ ] **Step 2: Write each env's state backend config**

```hcl
# infra/terraform/envs/dev/backend.tf
terraform {
  backend "s3" {
    bucket = "stock-research-terraform-state"
    key    = "dev/terraform.tfstate"
    region = "us-east-1"
  }
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = "us-east-1"
}
```

(`infra/terraform/envs/prod/backend.tf` is identical except `key = "prod/terraform.tfstate"`.)

Note: the `stock-research-terraform-state` S3 bucket and its DynamoDB lock table are themselves bootstrapped once, manually, before any other Terraform runs — this is the one narrow, standard exception to "no manual console changes," since Terraform cannot create the backend it stores its own state in without a chicken-and-egg problem. Document this as a one-time `terraform init`-adjacent setup step in `infra/terraform/README.md`, not a recurring manual process.

- [ ] **Step 3: Validate**

Run: `cd infra/terraform/envs/dev && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

```bash
git add infra/terraform/modules/network infra/terraform/envs/dev/backend.tf infra/terraform/envs/prod/backend.tf
git commit -m "feat: add Terraform network module and per-env state backends"
```

### Task 41: IAM module — EC2 instance profile for Bedrock/DynamoDB/S3 access

Per spec §9: no IRSA without EKS, so pod AWS access comes from the instance profile attached to the worker nodes.

**Files:**
- Create: `infra/terraform/modules/iam/main.tf`, `variables.tf`, `outputs.tf`

**Interfaces:**
- Produces: module `iam` with input `env: string`, `dynamodb_table_arns: list(string)`, `s3_bucket_arn: string`; output `instance_profile_name`.

- [ ] **Step 1: Write the module**

```hcl
# infra/terraform/modules/iam/variables.tf
variable "env" { type = string }
variable "dynamodb_table_arns" { type = list(string) }
variable "s3_bucket_arn" { type = string }
```

```hcl
# infra/terraform/modules/iam/main.tf
resource "aws_iam_role" "node_role" {
  name = "stock-research-${var.env}-node-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "app_access" {
  name = "stock-research-${var.env}-app-access"
  role = aws_iam_role.node_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "BedrockInvoke"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = "arn:aws:bedrock:us-east-1::foundation-model/us.anthropic.claude-haiku-4-5-20251001-v1:0"
      },
      {
        Sid      = "DynamoDBAccess"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
        Resource = var.dynamodb_table_arns
      },
      {
        Sid      = "S3ToolPayloadAccess"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "node_profile" {
  name = "stock-research-${var.env}-node-profile"
  role = aws_iam_role.node_role.name
}
```

```hcl
# infra/terraform/modules/iam/outputs.tf
output "instance_profile_name" {
  value = aws_iam_instance_profile.node_profile.name
}
```

- [ ] **Step 2: Validate**

Run: `cd infra/terraform/envs/dev && terraform validate`
Expected: `Success! The configuration is valid.` (module isn't instantiated in `envs/dev/main.tf` yet — that happens in Task 44 once all modules exist)

- [ ] **Step 3: Commit**

```bash
git add infra/terraform/modules/iam
git commit -m "feat: add Terraform IAM module for the EC2 instance-profile role"
```

### Task 42: DynamoDB module

**Files:**
- Create: `infra/terraform/modules/dynamodb/main.tf`, `variables.tf`, `outputs.tf`

**Interfaces:**
- Produces: module `dynamodb` with input `env: string`; outputs `table_arns: list(string)`, `tool_results_table_name`, `agent_outputs_table_name`, `process_history_table_name`. Table key schemas match Task 2's `TABLE_DEFINITIONS` exactly.

- [ ] **Step 1: Write the module**

```hcl
# infra/terraform/modules/dynamodb/variables.tf
variable "env" { type = string }
```

```hcl
# infra/terraform/modules/dynamodb/main.tf
resource "aws_dynamodb_table" "tool_results" {
  name         = "ToolResults-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "agent_outputs" {
  name         = "AgentOutputs-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "symbol"
  range_key    = "agent_name"
  attribute {
    name = "symbol"
    type = "S"
  }
  attribute {
    name = "agent_name"
    type = "S"
  }
}

resource "aws_dynamodb_table" "process_history" {
  name         = "ProcessHistory-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "symbol"
  range_key    = "sk"
  attribute {
    name = "symbol"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
}
```

```hcl
# infra/terraform/modules/dynamodb/outputs.tf
output "table_arns" {
  value = [aws_dynamodb_table.tool_results.arn, aws_dynamodb_table.agent_outputs.arn, aws_dynamodb_table.process_history.arn]
}

output "tool_results_table_name" {
  value = aws_dynamodb_table.tool_results.name
}

output "agent_outputs_table_name" {
  value = aws_dynamodb_table.agent_outputs.name
}

output "process_history_table_name" {
  value = aws_dynamodb_table.process_history.name
}
```

- [ ] **Step 2: Validate and commit**

Run: `cd infra/terraform/envs/dev && terraform validate`
Expected: `Success! The configuration is valid.`

```bash
git add infra/terraform/modules/dynamodb
git commit -m "feat: add Terraform DynamoDB module (three tables, per-env)"
```

### Task 43: S3 module for oversized tool payloads

**Files:**
- Create: `infra/terraform/modules/s3/main.tf`, `variables.tf`, `outputs.tf`

**Interfaces:**
- Produces: module `s3` with input `env: string`; outputs `bucket_arn`, `bucket_name`.

- [ ] **Step 1: Write the module**

```hcl
# infra/terraform/modules/s3/variables.tf
variable "env" { type = string }
```

```hcl
# infra/terraform/modules/s3/main.tf
resource "aws_s3_bucket" "tool_payloads" {
  bucket = "stock-research-tool-payloads-${var.env}"
}

resource "aws_s3_bucket_lifecycle_configuration" "expire_old_payloads" {
  bucket = aws_s3_bucket.tool_payloads.id
  rule {
    id     = "expire-after-30-days"
    status = "Enabled"
    expiration {
      days = 30  # payloads are re-fetched well before this per their own TTL; this is a backstop
    }
  }
}

resource "aws_s3_bucket_public_access_block" "block_all" {
  bucket                  = aws_s3_bucket.tool_payloads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

```hcl
# infra/terraform/modules/s3/outputs.tf
output "bucket_arn" {
  value = aws_s3_bucket.tool_payloads.arn
}

output "bucket_name" {
  value = aws_s3_bucket.tool_payloads.bucket
}
```

- [ ] **Step 2: Validate and commit**

Run: `cd infra/terraform/envs/dev && terraform validate`
Expected: `Success! The configuration is valid.`

```bash
git add infra/terraform/modules/s3
git commit -m "feat: add Terraform S3 module for oversized tool payloads"
```

### Task 44: EC2 cluster module and env wiring

**Files:**
- Create: `infra/terraform/modules/cluster/main.tf`, `variables.tf`, `outputs.tf`, `bootstrap.sh.tpl`
- Create: `infra/terraform/envs/dev/main.tf`
- Create: `infra/terraform/envs/prod/main.tf`

**Interfaces:**
- Produces: module `cluster` with inputs `env`, `vpc_id`, `subnet_ids`, `instance_profile_name`; outputs `control_plane_public_ip`, `worker_public_ips`. Each env's `main.tf` instantiates `network`, `iam`, `dynamodb`, `s3`, `cluster` together.

- [ ] **Step 1: Write the cluster bootstrap script template (k3s — a lighter self-managed distribution than raw kubeadm, still "Kubernetes on self-managed EC2, no EKS")**

```bash
# infra/terraform/modules/cluster/bootstrap.sh.tpl
#!/bin/bash
set -euo pipefail
if [ "${role}" = "control-plane" ]; then
  curl -sfL https://get.k3s.io | sh -s - server --write-kubeconfig-mode 644
else
  curl -sfL https://get.k3s.io | K3S_URL=https://${control_plane_ip}:6443 K3S_TOKEN=${cluster_token} sh -
fi
```

- [ ] **Step 2: Write the cluster module**

```hcl
# infra/terraform/modules/cluster/variables.tf
variable "env" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "instance_profile_name" { type = string }
variable "instance_type" {
  type    = string
  default = "t3.medium"
}
variable "cluster_token" {
  type      = string
  sensitive = true
}
```

```hcl
# infra/terraform/modules/cluster/main.tf
resource "aws_security_group" "cluster" {
  name   = "stock-research-${var.env}-cluster"
  vpc_id = var.vpc_id

  ingress {
    from_port = 22
    to_port   = 22
    protocol  = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # tighten to a known IP range before real deployment
  }
  ingress {
    from_port = 80
    to_port   = 80
    protocol  = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port = 6443
    to_port   = 6443
    protocol  = "tcp"
    self      = true
  }
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

resource "aws_instance" "control_plane" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.cluster.id]
  iam_instance_profile   = var.instance_profile_name
  user_data = templatefile("${path.module}/bootstrap.sh.tpl", {
    role = "control-plane", control_plane_ip = "", cluster_token = var.cluster_token
  })
  tags = { Name = "stock-research-${var.env}-control-plane" }
}

resource "aws_instance" "worker" {
  count                  = 2
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_ids[count.index % length(var.subnet_ids)]
  vpc_security_group_ids = [aws_security_group.cluster.id]
  iam_instance_profile   = var.instance_profile_name
  user_data = templatefile("${path.module}/bootstrap.sh.tpl", {
    role = "worker", control_plane_ip = aws_instance.control_plane.private_ip, cluster_token = var.cluster_token
  })
  tags = { Name = "stock-research-${var.env}-worker-${count.index}" }

  depends_on = [aws_instance.control_plane]
}
```

```hcl
# infra/terraform/modules/cluster/outputs.tf
output "control_plane_public_ip" {
  value = aws_instance.control_plane.public_ip
}

output "worker_public_ips" {
  value = aws_instance.worker[*].public_ip
}

output "elb_dns_name" {
  value = aws_elb.ingress.dns_name
}
```

Note on spec §9's "Nginx Ingress + ELB": this is a self-managed cluster with no cloud-controller-manager, so a Kubernetes `Service` of `type: LoadBalancer` cannot provision an ELB itself the way it would on EKS — it would just sit in `Pending` forever. Instead, ingress-nginx is installed as a `NodePort` service on fixed ports (Task 49 updates the install command accordingly), and Terraform provisions the ELB directly, targeting those NodePorts on both worker instances:

```hcl
# append to infra/terraform/modules/cluster/main.tf
resource "aws_elb" "ingress" {
  name    = "stock-research-${var.env}-ingress"
  subnets = var.subnet_ids

  listener {
    instance_port     = 30080  # ingress-nginx's fixed NodePort, set at install time (Task 49)
    instance_protocol = "http"
    lb_port            = 80
    lb_protocol         = "http"
  }

  health_check {
    target              = "HTTP:30080/healthz"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  instances                  = aws_instance.worker[*].id
  cross_zone_load_balancing  = true
  security_groups            = [aws_security_group.cluster.id]
}
```

The `cluster` security group (defined earlier in this same file) already allows inbound `:80` from `0.0.0.0/0`, which now also covers ELB→worker-node health checks and traffic on port 30080 in effect, since NodePort traffic arrives at the node's public IP; add an explicit ingress rule for `30080` to the same security group if a tighter default is used later.

- [ ] **Step 3: Wire everything together per environment**

```hcl
# infra/terraform/envs/dev/main.tf (envs/prod/main.tf is identical with env = "prod")
module "network" {
  source = "../../modules/network"
  env    = "dev"
}

module "s3" {
  source = "../../modules/s3"
  env    = "dev"
}

module "dynamodb" {
  source = "../../modules/dynamodb"
  env    = "dev"
}

module "iam" {
  source              = "../../modules/iam"
  env                 = "dev"
  dynamodb_table_arns = module.dynamodb.table_arns
  s3_bucket_arn       = module.s3.bucket_arn
}

variable "cluster_token" {
  type      = string
  sensitive = true
}

module "cluster" {
  source                 = "../../modules/cluster"
  env                     = "dev"
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.public_subnet_ids
  instance_profile_name   = module.iam.instance_profile_name
  cluster_token           = var.cluster_token
}

output "control_plane_public_ip" {
  value = module.cluster.control_plane_public_ip
}

output "elb_dns_name" {
  value = module.cluster.elb_dns_name
}
```

- [ ] **Step 4: Validate**

Run: `cd infra/terraform/envs/dev && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 5: Commit**

```bash
git add infra/terraform/modules/cluster infra/terraform/envs/dev/main.tf infra/terraform/envs/prod/main.tf
git commit -m "feat: add Terraform EC2 cluster module (k3s bootstrap) and wire dev/prod envs"
```

### Task 45: Apply `dev` and verify the cluster is reachable

- [ ] **Step 1: Plan and apply**

Run: `cd infra/terraform/envs/dev && terraform plan -out=tfplan && terraform apply tfplan`
Expected: apply succeeds; outputs include `control_plane_public_ip`

- [ ] **Step 2: Fetch the kubeconfig and verify the cluster is up**

Run: `scp ubuntu@<control_plane_public_ip>:/etc/rancher/k3s/k3s.yaml ~/.kube/config-dev && KUBECONFIG=~/.kube/config-dev kubectl get nodes`
Expected: 3 nodes (1 control-plane + 2 workers), all `Ready` (allow a few minutes after apply for worker bootstrap)

- [ ] **Step 3: Commit** (no file changes — this task is a verification checkpoint before Phase L)

No commit — this step only verifies infrastructure state.

---

## Phase L — Kubernetes / Helm

Each workload gets its own chart under `infra/k8s/helm/`. `dev` and `prod` are separate namespaces with separate values files (spec §9) — not separate charts.

### Task 46: MCP Server Helm chart

**Files:**
- Create: `infra/k8s/helm/mcp-server/Chart.yaml`, `values.yaml`, `templates/deployment.yaml`, `templates/service.yaml`, `templates/hpa.yaml`, `templates/secret.yaml`, `templates/configmap.yaml`

**Interfaces:**
- Produces: a chart deployable as `helm upgrade --install mcp-server infra/k8s/helm/mcp-server -n dev -f infra/k8s/helm/mcp-server/values-dev.yaml`

- [ ] **Step 1: Write `Chart.yaml` and `values.yaml`**

```yaml
# infra/k8s/helm/mcp-server/Chart.yaml
apiVersion: v2
name: mcp-server
version: 0.1.0
```

```yaml
# infra/k8s/helm/mcp-server/values.yaml
image: "<ECR_REPO>/mcp-server"
tag: "latest"
replicas: 2
resources:
  requests: { cpu: "100m", memory: "256Mi" }
  limits: { cpu: "500m", memory: "512Mi" }
hpa:
  minReplicas: 1
  maxReplicas: 3
  targetCPUUtilization: 70
```

- [ ] **Step 2: Write the Deployment, Service, HPA, ConfigMap, and Secret templates**

```yaml
# infra/k8s/helm/mcp-server/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-server
spec:
  replicas: {{ .Values.replicas }}
  selector:
    matchLabels: { app: mcp-server }
  template:
    metadata:
      labels: { app: mcp-server }
    spec:
      containers:
        - name: mcp-server
          image: "{{ .Values.image }}:{{ .Values.tag }}"
          ports: [{ containerPort: 8001 }]
          envFrom:
            - configMapRef: { name: mcp-server-config }
            - secretRef: { name: mcp-server-secrets }
          resources: {{ toYaml .Values.resources | nindent 12 }}
          livenessProbe:
            httpGet: { path: /healthz, port: 8001 }
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet: { path: /healthz, port: 8001 }
            initialDelaySeconds: 5
            periodSeconds: 5
```

```yaml
# infra/k8s/helm/mcp-server/templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: mcp-server
spec:
  selector: { app: mcp-server }
  ports: [{ port: 8001, targetPort: 8001 }]
```

```yaml
# infra/k8s/helm/mcp-server/templates/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: mcp-server
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: mcp-server }
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: {{ .Values.hpa.targetCPUUtilization }} }
```

```yaml
# infra/k8s/helm/mcp-server/templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-server-config
data:
  AWS_REGION: "us-east-1"
```

```yaml
# infra/k8s/helm/mcp-server/templates/secret.yaml
# Populated by CI (Task 51) from GitHub Actions secrets — this template defines the shape,
# not literal key material (per spec §9: provider API keys are namespace-scoped K8s Secrets).
apiVersion: v1
kind: Secret
metadata:
  name: mcp-server-secrets
type: Opaque
stringData:
  FINNHUB_API_KEY: "{{ .Values.finnhubApiKey }}"
  FMP_API_KEY: "{{ .Values.fmpApiKey }}"
  FRED_API_KEY: "{{ .Values.fredApiKey }}"
  MARKETAUX_API_KEY: "{{ .Values.marketauxApiKey }}"
  TOOL_PAYLOADS_BUCKET: "{{ .Values.toolPayloadsBucket }}"
```

- [ ] **Step 3: Lint and template-render the chart**

Run: `helm lint infra/k8s/helm/mcp-server && helm template infra/k8s/helm/mcp-server`
Expected: no lint errors; rendered manifests are valid YAML

- [ ] **Step 4: Commit**

```bash
git add infra/k8s/helm/mcp-server
git commit -m "feat: add MCP server Helm chart"
```

### Task 47: Scheduler Helm chart — heartbeat liveness probe, fixed single replica, no HPA

The one chart that must diverge from the others per spec §2.2/§9/§10: `replicas: 1` hardcoded (no HPA template at all), and a liveness probe that checks `/healthz` (Task 25's heartbeat endpoint) with a `failureThreshold`/`periodSeconds` combination tuned to the scheduler's own tick cadence rather than a generic quick-fail check.

**Files:**
- Create: `infra/k8s/helm/scheduler/Chart.yaml`, `values.yaml`, `templates/deployment.yaml`, `templates/configmap.yaml`, `templates/secret.yaml`

- [ ] **Step 1: Write `Chart.yaml` and `values.yaml`**

```yaml
# infra/k8s/helm/scheduler/Chart.yaml
apiVersion: v2
name: scheduler
version: 0.1.0
```

```yaml
# infra/k8s/helm/scheduler/values.yaml
image: "<ECR_REPO>/scheduler"
tag: "latest"
resources:
  requests: { cpu: "200m", memory: "512Mi" }
  limits: { cpu: "1000m", memory: "1Gi" }
```

Note there is no `hpa:` key and no `templates/hpa.yaml` in this chart — this is deliberate, not an oversight (spec §2.2, §9).

- [ ] **Step 2: Write the Deployment with the heartbeat liveness probe**

```yaml
# infra/k8s/helm/scheduler/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: scheduler
spec:
  replicas: 1  # hardcoded, not templated from values — never HPA-scaled, per spec §2.2/§9/§10
  strategy:
    type: Recreate  # avoid two schedulers running briefly during a rolling update
  selector:
    matchLabels: { app: scheduler }
  template:
    metadata:
      labels: { app: scheduler }
    spec:
      containers:
        - name: scheduler
          image: "{{ .Values.image }}:{{ .Values.tag }}"
          ports: [{ containerPort: 8002 }]
          envFrom:
            - configMapRef: { name: scheduler-config }
            - secretRef: { name: scheduler-secrets }
          resources: {{ toYaml .Values.resources | nindent 12 }}
          livenessProbe:
            # Heartbeat check (Task 25), not a generic process-alive check: the tick interval
            # is 60s and max staleness is 180s, so failureThreshold*periodSeconds must clear
            # 180s before Kubernetes restarts a scheduler that's merely between ticks.
            httpGet: { path: /healthz, port: 8002 }
            initialDelaySeconds: 30
            periodSeconds: 30
            failureThreshold: 3
          readinessProbe:
            httpGet: { path: /healthz, port: 8002 }
            initialDelaySeconds: 10
            periodSeconds: 10
```

```yaml
# infra/k8s/helm/scheduler/templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: scheduler-config
data:
  AWS_REGION: "us-east-1"
  OWN_MCP_SERVER_URL: "http://mcp-server:8001/mcp"
  TRADINGVIEW_MCP_URL: "{{ .Values.tradingviewMcpUrl }}"
  STOCK_SCANNER_MCP_URL: "{{ .Values.stockScannerMcpUrl }}"
```

```yaml
# infra/k8s/helm/scheduler/templates/secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: scheduler-secrets
type: Opaque
stringData:
  TOOL_PAYLOADS_BUCKET: "{{ .Values.toolPayloadsBucket }}"
```

- [ ] **Step 3: Lint and commit**

Run: `helm lint infra/k8s/helm/scheduler && helm template infra/k8s/helm/scheduler`
Expected: no lint errors; rendered Deployment shows `replicas: 1` and no HPA object anywhere in the output

```bash
git add infra/k8s/helm/scheduler
git commit -m "feat: add Scheduler Helm chart with fixed single replica and heartbeat liveness probe"
```

### Task 48: API Backend Helm chart

**Files:**
- Create: `infra/k8s/helm/api-backend/Chart.yaml`, `values.yaml`, `templates/deployment.yaml`, `templates/service.yaml`, `templates/hpa.yaml`, `templates/configmap.yaml`

- [ ] **Step 1: Write the chart (same shape as Task 46's mcp-server chart — HPA-backed, standard liveness/readiness)**

```yaml
# infra/k8s/helm/api-backend/Chart.yaml
apiVersion: v2
name: api-backend
version: 0.1.0
```

```yaml
# infra/k8s/helm/api-backend/values.yaml
image: "<ECR_REPO>/api-backend"
tag: "latest"
replicas: 2
resources:
  requests: { cpu: "200m", memory: "256Mi" }
  limits: { cpu: "500m", memory: "512Mi" }
hpa:
  minReplicas: 2
  maxReplicas: 4
  targetCPUUtilization: 70
```

```yaml
# infra/k8s/helm/api-backend/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-backend
spec:
  replicas: {{ .Values.replicas }}
  selector:
    matchLabels: { app: api-backend }
  template:
    metadata:
      labels: { app: api-backend }
    spec:
      containers:
        - name: api-backend
          image: "{{ .Values.image }}:{{ .Values.tag }}"
          ports: [{ containerPort: 8080 }]
          envFrom:
            - configMapRef: { name: api-backend-config }
          resources: {{ toYaml .Values.resources | nindent 12 }}
          livenessProbe:
            httpGet: { path: /healthz, port: 8080 }
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet: { path: /healthz, port: 8080 }
            initialDelaySeconds: 5
            periodSeconds: 5
```

```yaml
# infra/k8s/helm/api-backend/templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: api-backend
spec:
  selector: { app: api-backend }
  ports: [{ port: 8080, targetPort: 8080 }]
```

```yaml
# infra/k8s/helm/api-backend/templates/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-backend
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: api-backend }
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: {{ .Values.hpa.targetCPUUtilization }} }
```

```yaml
# infra/k8s/helm/api-backend/templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: api-backend-config
data:
  AWS_REGION: "us-east-1"
  OWN_MCP_SERVER_URL: "http://mcp-server:8001/mcp"
```

- [ ] **Step 2: Lint and commit**

Run: `helm lint infra/k8s/helm/api-backend`
Expected: no lint errors

```bash
git add infra/k8s/helm/api-backend
git commit -m "feat: add API Backend Helm chart"
```

### Task 49: Frontend Helm chart and Ingress

**Files:**
- Create: `infra/k8s/helm/frontend/Chart.yaml`, `values.yaml`, `templates/deployment.yaml`, `templates/service.yaml`, `templates/hpa.yaml`, `templates/ingress.yaml`

- [ ] **Step 1: Write the chart**

```yaml
# infra/k8s/helm/frontend/Chart.yaml
apiVersion: v2
name: frontend
version: 0.1.0
```

```yaml
# infra/k8s/helm/frontend/values.yaml
image: "<ECR_REPO>/frontend"
tag: "latest"
replicas: 2
host: "dev.stock-research.example"
resources:
  requests: { cpu: "50m", memory: "64Mi" }
  limits: { cpu: "200m", memory: "128Mi" }
hpa:
  minReplicas: 1
  maxReplicas: 3
  targetCPUUtilization: 70
```

```yaml
# infra/k8s/helm/frontend/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
spec:
  replicas: {{ .Values.replicas }}
  selector:
    matchLabels: { app: frontend }
  template:
    metadata:
      labels: { app: frontend }
    spec:
      containers:
        - name: frontend
          image: "{{ .Values.image }}:{{ .Values.tag }}"
          ports: [{ containerPort: 80 }]
          resources: {{ toYaml .Values.resources | nindent 12 }}
          livenessProbe:
            httpGet: { path: /, port: 80 }
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet: { path: /, port: 80 }
            initialDelaySeconds: 5
            periodSeconds: 5
```

```yaml
# infra/k8s/helm/frontend/templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: frontend
spec:
  selector: { app: frontend }
  ports: [{ port: 80, targetPort: 80 }]
```

```yaml
# infra/k8s/helm/frontend/templates/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: frontend
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: frontend }
  minReplicas: {{ .Values.hpa.minReplicas }}
  maxReplicas: {{ .Values.hpa.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: {{ .Values.hpa.targetCPUUtilization }} }
```

```yaml
# infra/k8s/helm/frontend/templates/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: frontend
  annotations:
    nginx.ingress.kubernetes.io/proxy-buffering: "off"  # required for SSE endpoints proxied through
spec:
  ingressClassName: nginx
  rules:
    - host: "{{ .Values.host }}"
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: frontend, port: { number: 80 } }
```

- [ ] **Step 2: Lint and commit**

Run: `helm lint infra/k8s/helm/frontend`
Expected: no lint errors

```bash
git add infra/k8s/helm/frontend
git commit -m "feat: add Frontend Helm chart with SSE-safe Nginx Ingress"
```

- [ ] **Step 3: Install ingress-nginx itself on the cluster (one-time per cluster, not per app deploy), as a NodePort service on the fixed port the ELB (Task 44) targets**

Run: `KUBECONFIG=~/.kube/config-dev helm install ingress-nginx ingress-nginx --repo https://kubernetes.github.io/ingress-nginx --namespace ingress-nginx --create-namespace --set controller.service.type=NodePort --set controller.service.nodePorts.http=30080`
Expected: `ingress-nginx-controller` pod reaches `Running`; `kubectl -n ingress-nginx get svc` shows the Service with port `80:30080/TCP` — this is the NodePort the ELB's listener (Task 44) forwards to, since a plain `LoadBalancer`-type Service can't provision an ELB itself without a cloud-controller-manager on this self-managed cluster.

- [ ] **Step 4: Create the `dev` and `prod` namespaces**

Run: `KUBECONFIG=~/.kube/config-dev kubectl create namespace dev && kubectl create namespace prod`
Expected: both namespaces created

---

## Phase M — CI/CD

Per spec §9: PR checks run tests; merge to `main` auto-deploys `dev`; `prod` is ArgoCD-managed, gated by manual approval.

### Task 50: PR workflow — lint, unit tests, MCP integration tests, job summary

**Files:**
- Create: `.github/workflows/pr-checks.yml`

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/pr-checks.yml
name: PR Checks
on:
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [mcp-server, scheduler, api-backend, common]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Install service
        working-directory: ${{ matrix.service == 'common' && 'packages/common' || format('services/{0}', matrix.service) }}
        run: pip install -e ".[dev]"
      - name: Install common (path dependency, for services other than common itself)
        if: matrix.service != 'common'
        run: pip install -e packages/common
      - name: Run tests
        working-directory: ${{ matrix.service == 'common' && 'packages/common' || format('services/{0}', matrix.service) }}
        run: pytest --junitxml=results.xml -v
      - name: Publish test results to job summary
        if: always()
        uses: EnricoMi/publish-unit-test-result-action@v2
        with:
          files: "**/results.xml"

  frontend-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - working-directory: frontend
        run: npm ci && npm run lint && npx vitest run

  helm-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-helm@v4
      - run: |
          for chart in infra/k8s/helm/*/; do helm lint "$chart"; done

  terraform-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - working-directory: infra/terraform/envs/dev
        run: terraform init -backend=false && terraform validate
```

- [ ] **Step 2: Verify locally as much as possible (the workflow itself can only be fully verified by opening a PR)**

Run: `act pull_request -W .github/workflows/pr-checks.yml` (if `act` is available locally) or open a draft PR after committing and confirm all four jobs run and pass in the GitHub Actions tab.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/pr-checks.yml
git commit -m "ci: add PR checks workflow (unit tests, MCP integration tests, lint, job summary)"
```

### Task 51: `dev` auto-deploy workflow

**Files:**
- Create: `.github/workflows/deploy-dev.yml`

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/deploy-dev.yml
name: Deploy to dev
on:
  push:
    branches: [main]

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [mcp-server, scheduler, api-backend, frontend]
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_CI_ROLE_ARN }}
          aws-region: us-east-1
      - uses: aws-actions/amazon-ecr-login@v2
        id: ecr
      - name: Build and push
        run: |
          docker build -f services/${{ matrix.service }}/Dockerfile -t ${{ steps.ecr.outputs.registry }}/${{ matrix.service }}:${{ github.sha }} .
          docker push ${{ steps.ecr.outputs.registry }}/${{ matrix.service }}:${{ github.sha }}
        if: matrix.service != 'frontend'
      - name: Build and push frontend
        run: |
          docker build -f frontend/Dockerfile -t ${{ steps.ecr.outputs.registry }}/frontend:${{ github.sha }} .
          docker push ${{ steps.ecr.outputs.registry }}/frontend:${{ github.sha }}
        if: matrix.service == 'frontend'

  deploy-dev:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/setup-helm@v4
      - name: Configure kubeconfig
        run: echo "${{ secrets.KUBECONFIG_DEV }}" | base64 -d > $HOME/.kube/config
      - name: Deploy each chart
        run: |
          for chart in mcp-server scheduler api-backend frontend; do
            helm upgrade --install "$chart" "infra/k8s/helm/$chart" \
              -n dev -f "infra/k8s/helm/$chart/values-dev.yaml" \
              --set tag=${{ github.sha }} --wait --timeout 5m
          done
      - name: Run smoke test against dev
        run: |
          chmod +x scripts/smoke_test.sh
          DEV_HOST=dev.stock-research.example ./scripts/smoke_test.sh
```

- [ ] **Step 2: Write per-env Helm values files referenced above**

```yaml
# infra/k8s/helm/mcp-server/values-dev.yaml (analogous values-dev.yaml added for scheduler, api-backend, frontend)
image: "<ECR_REPO>/mcp-server"
replicas: 1
hpa:
  minReplicas: 1
  maxReplicas: 2
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy-dev.yml infra/k8s/helm/*/values-dev.yaml
git commit -m "ci: add dev auto-deploy workflow triggered on merge to main"
```

### Task 52: ArgoCD install and `prod` promotion workflow

Per the agreed design: `prod` is ArgoCD-managed (GitOps, pull-based), gated by manual approval — not a second push-based GitHub Actions deploy job.

**Files:**
- Create: `infra/k8s/argocd/applications/mcp-server-prod.yaml`, `scheduler-prod.yaml`, `api-backend-prod.yaml`, `frontend-prod.yaml`
- Create: `.github/workflows/promote-prod.yml`

- [ ] **Step 1: Install ArgoCD on the cluster (one-time)**

Run: `KUBECONFIG=~/.kube/config-dev kubectl create namespace argocd && kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml`
Expected: ArgoCD pods reach `Running` in the `argocd` namespace

- [ ] **Step 2: Write an ArgoCD `Application` per workload, pointed at the `prod` values file in this repo**

```yaml
# infra/k8s/argocd/applications/api-backend-prod.yaml (same shape for the other 3 workloads)
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: api-backend-prod
  namespace: argocd
spec:
  project: default
  source:
    repoURL: <THIS_REPO_URL>
    targetRevision: main
    path: infra/k8s/helm/api-backend
    helm:
      valueFiles: ["values-prod.yaml"]
  destination:
    server: https://kubernetes.default.svc
    namespace: prod
  syncPolicy: {}  # deliberately no automated: {} block — sync stays manual, gated by approval
```

- [ ] **Step 3: Write matching `values-prod.yaml` files for each chart**

```yaml
# infra/k8s/helm/api-backend/values-prod.yaml (analogous for the other 3 charts)
image: "<ECR_REPO>/api-backend"
replicas: 2
hpa:
  minReplicas: 2
  maxReplicas: 4
```

- [ ] **Step 4: Write the promotion workflow — updates the prod image tag, requires a GitHub Environment approval, then triggers the ArgoCD sync**

```yaml
# .github/workflows/promote-prod.yml
name: Promote to prod
on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: "Image tag (git SHA) to promote — must already be deployed and verified in dev"
        required: true

jobs:
  promote:
    runs-on: ubuntu-latest
    environment: production  # GitHub Environment with required reviewers configured — the manual gate
    steps:
      - uses: actions/checkout@v4
      - name: Update prod values files to the promoted tag
        run: |
          for chart in mcp-server scheduler api-backend frontend; do
            sed -i "s/^tag: .*/tag: \"${{ inputs.image_tag }}\"/" "infra/k8s/helm/$chart/values-prod.yaml"
          done
      - name: Commit the tag bump
        run: |
          git config user.name "github-actions"
          git config user.email "github-actions@users.noreply.github.com"
          git add infra/k8s/helm/*/values-prod.yaml
          git commit -m "chore: promote ${{ inputs.image_tag }} to prod"
          git push
      - name: Trigger ArgoCD sync
        run: |
          argocd app sync mcp-server-prod scheduler-prod api-backend-prod frontend-prod \
            --server ${{ secrets.ARGOCD_SERVER }} --auth-token ${{ secrets.ARGOCD_AUTH_TOKEN }}
```

- [ ] **Step 5: Commit**

```bash
git add infra/k8s/argocd infra/k8s/helm/*/values-prod.yaml .github/workflows/promote-prod.yml
git commit -m "ci: add ArgoCD Applications and manually-gated prod promotion workflow"
```

### Task 53: Wire the end-to-end smoke test into the `dev` deploy workflow

Already referenced in Task 51's `deploy-dev.yml` (`Run smoke test against dev` step). This task adapts `scripts/smoke_test.sh` (Task 39) to target the deployed `dev` host instead of `localhost`, satisfying spec §11's end-to-end smoke test requirement.

**Files:**
- Modify: `scripts/smoke_test.sh`

- [ ] **Step 1: Parameterize the script's base URL**

```bash
# modify scripts/smoke_test.sh — replace hardcoded localhost URLs
BASE_URL="${DEV_HOST:+https://${DEV_HOST}/api}"
BASE_URL="${BASE_URL:-http://localhost:8000/api}"
# then replace every http://localhost:8000/api/... call in the script with "$BASE_URL/..."
```

- [ ] **Step 2: Verify it still passes locally with the default (unset `DEV_HOST`)**

Run: `./scripts/smoke_test.sh`
Expected: same pass behavior as Task 39, now via the parameterized `BASE_URL`

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_test.sh
git commit -m "ci: parameterize smoke test to target either localhost or a deployed dev host"
```

---

## Phase N — Observability

### Task 54: kube-prometheus-stack and Loki

**Files:**
- Create: `monitoring/prometheus/values.yaml`
- Create: `monitoring/prometheus/servicemonitors.yaml`

- [ ] **Step 1: Install kube-prometheus-stack**

```yaml
# monitoring/prometheus/values.yaml
grafana:
  adminPassword: "<set via --set on install, not committed>"
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false  # pick up ServiceMonitors from any namespace
```

Run: `KUBECONFIG=~/.kube/config-dev helm install kube-prometheus-stack kube-prometheus-stack --repo https://prometheus-community.github.io/helm-charts --namespace monitoring --create-namespace -f monitoring/prometheus/values.yaml`
Expected: Prometheus, Grafana, and Alertmanager pods reach `Running` in the `monitoring` namespace

- [ ] **Step 2: Install Loki + Promtail for log aggregation**

Run: `helm install loki loki-stack --repo https://grafana.github.io/helm-charts --namespace monitoring`
Expected: `loki` and `promtail` pods reach `Running`

- [ ] **Step 3: Write ServiceMonitors for the four workloads (each app must also expose a `/metrics` endpoint — added via `prometheus-fastapi-instrumentator` for api-backend/mcp-server, and a small custom counter set in the scheduler's health server for scheduler-specific metrics: tick duration, tools fetched, cascades triggered)**

```yaml
# monitoring/prometheus/servicemonitors.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: stock-research-services
  namespace: monitoring
spec:
  namespaceSelector:
    matchNames: [dev, prod]
  selector:
    matchExpressions:
      - { key: app, operator: In, values: [mcp-server, api-backend, scheduler] }
  endpoints:
    - port: metrics
      interval: 30s
```

Note: each service's `Service` template (Tasks 46-48) needs a named `metrics` port added pointing at its `/metrics` endpoint — add `prometheus-fastapi-instrumentator` (api-backend, mcp-server, both FastAPI/FastMCP-adjacent) and a minimal `prometheus_client` counter/histogram set exposed from the scheduler's existing health HTTP server (Task 25) before this ServiceMonitor has anything real to scrape.

- [ ] **Step 4: Apply and verify**

Run: `kubectl apply -f monitoring/prometheus/servicemonitors.yaml && kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090`
Expected: targets for `mcp-server`, `api-backend`, `scheduler` show as `UP` at `http://localhost:9090/targets`

- [ ] **Step 5: Commit**

```bash
git add monitoring/prometheus
git commit -m "feat: install kube-prometheus-stack + Loki, add ServiceMonitors for all workloads"
```

### Task 55: Alertmanager rules

Per spec §9: alerts on error rate spikes, tool timeouts, circuit-breaker trips, and the scheduler falling behind its own cadence.

**Files:**
- Create: `monitoring/prometheus/rules/alerts.yaml`

- [ ] **Step 1: Write the PrometheusRule**

```yaml
# monitoring/prometheus/rules/alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: stock-research-alerts
  namespace: monitoring
spec:
  groups:
    - name: stock-research
      rules:
        - alert: HighErrorRate
          expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
          for: 5m
          labels: { severity: warning }
          annotations: { summary: "5xx rate above 5% for {{ $labels.app }}" }

        - alert: ToolCallTimeouts
          expr: increase(mcp_tool_call_timeouts_total[10m]) > 5
          for: 0m
          labels: { severity: warning }
          annotations: { summary: "More than 5 MCP tool-call timeouts in 10 minutes" }

        - alert: CircuitBreakerOpen
          expr: circuit_breaker_state{server=~"tradingview|stock_scanner"} == 1
          for: 5m
          labels: { severity: warning }
          annotations: { summary: "Shared TradingView circuit breaker has been open for 5+ minutes" }

        - alert: SchedulerHeartbeatStale
          expr: time() - scheduler_last_tick_timestamp_seconds > 180
          for: 1m
          labels: { severity: critical }
          annotations: { summary: "Scheduler heartbeat stale — the single-point-of-failure scheduler may be hung (spec §10)" }
```

Note: `mcp_tool_call_timeouts_total` and `circuit_breaker_state` require the Scheduler to export these as `prometheus_client` metrics (increment/set them at the same call sites as Task 5's `CircuitBreaker.record_failure`/`allow_call` and Task 14's `call_tool`); `scheduler_last_tick_timestamp_seconds` is a gauge set alongside Task 25's `record_heartbeat`.

- [ ] **Step 2: Apply and verify**

Run: `kubectl apply -f monitoring/prometheus/rules/alerts.yaml && kubectl -n monitoring get prometheusrule`
Expected: `stock-research-alerts` listed; rules visible (and evaluating without syntax errors) at `http://localhost:9090/rules`

- [ ] **Step 3: Commit**

```bash
git add monitoring/prometheus/rules
git commit -m "feat: add Alertmanager rules for error rate, tool timeouts, circuit breaker, scheduler heartbeat"
```

### Task 56: Langfuse Cloud integration

Per the agreed design: Langfuse Cloud (SaaS), not self-hosted — traces every LLM/tool call in the Scheduler's LangGraph pipeline and the API Backend's Chat.

**Files:**
- Modify: `services/scheduler/pyproject.toml`, `services/api-backend/pyproject.toml`
- Modify: `services/scheduler/src/graph/specialists.py`, `debate.py`, `risk.py` (add the Langfuse callback handler to each `ChatBedrockConverse` invocation)
- Modify: `services/api-backend/src/routers/chat.py`

- [ ] **Step 1: Add the dependency**

```toml
# add to services/scheduler/pyproject.toml and services/api-backend/pyproject.toml
dependencies = [
    # ...existing...
    "langfuse>=2.50",
]
```

- [ ] **Step 2: Add a shared callback-handler factory to `packages/common`**

```python
# packages/common/common/tracing.py
import os
from langfuse.callback import CallbackHandler

def langfuse_handler(session_id: str | None = None) -> CallbackHandler:
    return CallbackHandler(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host="https://cloud.langfuse.com",
        session_id=session_id,
    )
```

- [ ] **Step 3: Pass the handler into every LLM `.invoke(...)` call via `config`**

```python
# modify services/scheduler/src/graph/specialists.py — in _invoke_llm
from common.tracing import langfuse_handler

def _invoke_llm(system_prompt: str, tool_data: dict, symbol: str) -> dict:
    llm = ChatBedrockConverse(...).with_structured_output(SpecialistResponse)
    response = llm.invoke(
        [...],
        config={"callbacks": [langfuse_handler(session_id=symbol)], "tags": [system_prompt[:20]]},
    )
    return response.model_dump()
```

The same `config={"callbacks": [langfuse_handler(session_id=symbol)]}` pattern is applied to Task 19's `_invoke_bull_llm`/`_invoke_bear_llm`/`_invoke_bear_rebuttal_llm`, Task 20's `_invoke_risk_llm`, and Task 30's `_invoke_chat_llm` — every LLM call site in the system, so every model/tool call for a given symbol's pipeline run is grouped under one Langfuse session.

- [ ] **Step 4: Add the Langfuse credentials to each Secret template**

```yaml
# add to infra/k8s/helm/scheduler/templates/secret.yaml and api-backend's equivalent
  LANGFUSE_PUBLIC_KEY: "{{ .Values.langfusePublicKey }}"
  LANGFUSE_SECRET_KEY: "{{ .Values.langfuseSecretKey }}"
```

- [ ] **Step 5: Verify traces appear**

Run: locally, `docker compose up` with real Langfuse Cloud credentials in `.env`, trigger a pipeline run (via the smoke test), then check the Langfuse Cloud dashboard.
Expected: a trace appears showing the specialist/debate/risk/chat LLM calls for the test run, grouped by symbol

- [ ] **Step 6: Commit**

```bash
git add packages/common/common/tracing.py services/scheduler/pyproject.toml services/api-backend/pyproject.toml services/scheduler/src/graph services/api-backend/src/routers/chat.py infra/k8s/helm/*/templates/secret.yaml
git commit -m "feat: integrate Langfuse Cloud tracing across every LLM call site"
```

### Task 57: Grafana system-health dashboard

**Files:**
- Create: `monitoring/grafana/dashboards/system-health.json`

- [ ] **Step 1: Define the dashboard (panels: request latency/error rate per service, SQS — n/a, DynamoDB read/write capacity via CloudWatch if wired, circuit-breaker state, scheduler tick duration and heartbeat age, pod restart counts)**

```json
{
  "title": "Stock Research Agent — System Health",
  "panels": [
    { "title": "Request latency (p50/p95) by service", "targets": [{ "expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))" }] },
    { "title": "5xx error rate by service", "targets": [{ "expr": "rate(http_requests_total{status=~\"5..\"}[5m])" }] },
    { "title": "Circuit breaker state (0=closed,1=open,2=half_open)", "targets": [{ "expr": "circuit_breaker_state" }] },
    { "title": "Scheduler heartbeat age (seconds)", "targets": [{ "expr": "time() - scheduler_last_tick_timestamp_seconds" }] },
    { "title": "Pod restarts (last 1h)", "targets": [{ "expr": "increase(kube_pod_container_status_restarts_total{namespace=~\"dev|prod\"}[1h])" }] }
  ]
}
```

- [ ] **Step 2: Import into Grafana and verify each panel renders with live data**

Run: `kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3001:80`, log in, import `monitoring/grafana/dashboards/system-health.json`
Expected: all five panels render (populated once the smoke test has generated some traffic); note in the dashboard description that Langfuse Cloud's own UI is the companion view for trace-level agent debugging, per spec §9

- [ ] **Step 3: Commit**

```bash
git add monitoring/grafana/dashboards/system-health.json
git commit -m "feat: add Grafana system-health dashboard"
```
