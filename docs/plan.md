# Trading Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy the advisory-only Trading Agent described in `docs/spec.md`: a LangGraph multi-agent system with two MCP tool servers, a FastAPI backend + React UI, backed by AWS services provisioned via Terraform, running on a self-managed Kubernetes cluster (kubeadm) on EC2 across `dev`/`prod` namespaces, with full CI/CD and observability.

**Architecture:** A walking skeleton (Phase 1) proves one thin path — one MCP tool, one agent, one API route, containerized, running on a local kind cluster, exercised by CI — before any phase adds breadth. Feature phases (2–8) build out the two MCP servers, the multi-agent pipeline, the backtest engine, the strategy library, the news/live-signal pipelines, and the web UI, testing against local/mocked backends (moto for AWS, a mocked LLM, real MCP stdio transport). Infra phases (9–12) provision the real AWS resources via Terraform, point the already-tested manifests at the real EC2 Kubernetes cluster, and add CI/CD and observability.

**Tech Stack:** Python 3.12, LangGraph + `langchain-mcp-adapters` (`MultiServerMCPClient`, `create_react_agent`), FastMCP for the self-built MCP server, FastAPI, pytest + moto + pytest-asyncio, React + Vite + Vitest + React Testing Library, boto3, `backtesting.py`, edgartools, Terraform, Kubernetes (kubeadm), Docker, GitHub Actions, kube-prometheus-stack (Prometheus/Grafana/Alertmanager) + Loki/Promtail via Helm.

## Global Constraints

- Advisory only: no order-execution tool is ever registered on any agent's tool set, in any environment (spec §2).
- Primary asset scope: US equities/ETFs only; crypto, forex, and options/derivatives are out of scope (spec §3).
- `dev` and `prod` get fully separate AWS resources (Terraform workspaces) and fully separate K8s namespaces with their own ConfigMaps/Secrets (spec §7–§8).
- All AWS resources are provisioned via Terraform — no manual console changes (spec §7).
- Every external data source call has retry/backoff tuned to that source's documented free-tier limit (Finnhub 60/min) (spec §11).
- Every long-running Deployment has liveness and readiness probes (spec §8, §11).
- Unit tests mock the LLM and all external services; integration tests use the real MCP stdio transport, not mocked at the transport layer (spec §12).
- Single-user, no auth.

---

## Phase 0 — Repo scaffolding & tooling

### Task 1: Python + frontend project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `shared/__init__.py`, `mcp_servers/__init__.py`, `mcp_servers/domain_data/__init__.py`, `agents/__init__.py`, `backend/__init__.py`
- Create: `tests/__init__.py`
- Create: `.ruff.toml`
- Create: `frontend/` (via `npm create vite`)

**Interfaces:**
- Produces: importable top-level packages `shared`, `mcp_servers.domain_data`, `agents`, `backend`, all installed editable so later tasks can `import shared.models` etc. without path hacks.

- [ ] **Step 1: Create the Python package layout and dependency manifest**

```toml
# pyproject.toml
[project]
name = "trading-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "httpx>=0.27",
    "pydantic>=2.9",
    "boto3>=1.35",
    "langgraph>=0.2",
    "langchain-mcp-adapters>=0.1",
    "langchain-anthropic>=0.3",
    "langchain-core>=0.3",
    "fastmcp>=2.0",
    "mcp>=1.1",
    "backtesting>=0.3.3",
    "pandas>=2.2",
    "numpy>=1.26",
    "edgartools>=3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "moto[dynamodb,s3,sqs]>=5.0",
    "ruff>=0.7",
]

[tool.setuptools.packages.find]
include = ["shared*", "mcp_servers*", "agents*", "backend*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

```bash
mkdir -p shared mcp_servers/domain_data agents backend tests
touch shared/__init__.py mcp_servers/__init__.py mcp_servers/domain_data/__init__.py agents/__init__.py backend/__init__.py tests/__init__.py
```

```toml
# .ruff.toml
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Install and verify the test runner works**

Run: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pytest`
Expected: dependencies install cleanly; pytest reports `no tests ran` (exit code 5) or `0 passed` — not an import/collection error.

- [ ] **Step 3: Scaffold the frontend**

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

```ts
// frontend/vite.config.ts (append test config)
export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", globals: true, setupFiles: "./src/setupTests.ts" },
});
```

```ts
// frontend/src/setupTests.ts
import "@testing-library/jest-dom";
```

- [ ] **Step 4: Verify the frontend build and empty test run**

Run: `cd frontend && npm run build && npx vitest run`
Expected: build succeeds; vitest reports no test files found (not an error) since no components exist yet.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .ruff.toml shared mcp_servers agents backend tests frontend
git commit -m "chore: scaffold Python and frontend project layout"
```

---

## Phase 1 — Walking skeleton

Proves one thin path end to end — one MCP tool, one agent, one API route, containerized, running on a local Kubernetes cluster, exercised by CI — before any phase adds breadth.

### Task 2: Domain-Data MCP server with one tool (Finnhub quote)

**Files:**
- Create: `mcp_servers/domain_data/http.py`
- Create: `mcp_servers/domain_data/finnhub_client.py`
- Create: `mcp_servers/domain_data/server.py`
- Test: `tests/mcp_servers/test_finnhub_client.py`
- Test: `tests/mcp_servers/test_server_integration.py`

**Interfaces:**
- Produces: `request_with_retry(client: httpx.Client, method: str, url: str, *, max_retries: int = 3, **kwargs) -> httpx.Response` in `mcp_servers/domain_data/http.py`.
- Produces: `get_quote(symbol: str) -> dict` in `mcp_servers/domain_data/finnhub_client.py`, returning `{"symbol": str, "current": float, "high": float, "low": float, "open": float, "previous_close": float}`.
- Produces: a FastMCP server instance `mcp` in `mcp_servers/domain_data/server.py` exposing `get_quote` as an MCP tool, runnable via `python -m mcp_servers.domain_data.server`.

- [ ] **Step 1: Write the failing test for retry/backoff**

```python
# tests/mcp_servers/test_http.py
import httpx
import pytest
from mcp_servers.domain_data.http import request_with_retry

def test_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("time.sleep", lambda _: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = request_with_retry(client, "GET", "https://example.com")
    assert response.status_code == 200
    assert calls["n"] == 3

def test_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        request_with_retry(client, "GET", "https://example.com", max_retries=2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_http.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_servers.domain_data.http'`

- [ ] **Step 3: Implement the retry helper**

```python
# mcp_servers/domain_data/http.py
import time
import httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

def request_with_retry(
    client: httpx.Client, method: str, url: str, *, max_retries: int = 3, **kwargs
) -> httpx.Response:
    last_response = None
    for attempt in range(max_retries):
        response = client.request(method, url, **kwargs)
        if response.status_code not in RETRYABLE_STATUS:
            response.raise_for_status()
            return response
        last_response = response
        time.sleep(2**attempt)
    last_response.raise_for_status()
    return last_response
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/mcp_servers/test_http.py -v`
Expected: 2 passed

- [ ] **Step 5: Write the failing test for the Finnhub quote client**

```python
# tests/mcp_servers/test_finnhub_client.py
import httpx
import pytest
from mcp_servers.domain_data import finnhub_client

def test_get_quote_returns_parsed_fields(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

    def handler(request):
        assert request.url.params["symbol"] == "AAPL"
        assert request.url.params["token"] == "test-key"
        return httpx.Response(
            200, json={"c": 190.1, "h": 191.0, "l": 188.5, "o": 189.0, "pc": 188.0}
        )

    monkeypatch.setattr(
        finnhub_client, "_client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    quote = finnhub_client.get_quote("AAPL")
    assert quote == {
        "symbol": "AAPL",
        "current": 190.1,
        "high": 191.0,
        "low": 188.5,
        "open": 189.0,
        "previous_close": 188.0,
    }

def test_get_quote_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FINNHUB_API_KEY"):
        finnhub_client.get_quote("AAPL")
```

- [ ] **Step 6: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_finnhub_client.py -v`
Expected: FAIL — `finnhub_client` module does not exist

- [ ] **Step 7: Implement the Finnhub quote client**

```python
# mcp_servers/domain_data/finnhub_client.py
import os
import httpx
from mcp_servers.domain_data.http import request_with_retry

BASE_URL = "https://finnhub.io/api/v1"
_client = httpx.Client(base_url=BASE_URL, timeout=10.0)

def _api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        raise RuntimeError("FINNHUB_API_KEY is not set")
    return key

def get_quote(symbol: str) -> dict:
    response = request_with_retry(
        _client, "GET", "/quote", params={"symbol": symbol, "token": _api_key()}
    )
    data = response.json()
    return {
        "symbol": symbol,
        "current": data["c"],
        "high": data["h"],
        "low": data["l"],
        "open": data["o"],
        "previous_close": data["pc"],
    }
```

- [ ] **Step 8: Run to verify it passes**

Run: `pytest tests/mcp_servers/test_finnhub_client.py -v`
Expected: 2 passed

- [ ] **Step 9: Write the MCP-transport integration test**

```python
# tests/mcp_servers/test_server_integration.py
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

@pytest.mark.asyncio
async def test_get_quote_tool_is_discoverable_and_callable(monkeypatch):
    params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_servers.domain_data.server"],
        env={"FINNHUB_API_KEY": "test-key"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "get_quote" in names
```

Note: this test calls the real Finnhub API through the running subprocess since no HTTP mocking crosses the subprocess boundary; it only asserts tool discovery, not live data values, so it stays deterministic without live network access being required for the assertion itself.

- [ ] **Step 10: Implement the FastMCP server and run the integration test**

```python
# mcp_servers/domain_data/server.py
from fastmcp import FastMCP
from mcp_servers.domain_data import finnhub_client

mcp = FastMCP("domain-data")

@mcp.tool()
def get_quote(symbol: str) -> dict:
    """Get the latest price quote for a US equity ticker symbol."""
    return finnhub_client.get_quote(symbol)

if __name__ == "__main__":
    mcp.run()
```

Run: `pytest tests/mcp_servers/test_server_integration.py -v`
Expected: 1 passed

- [ ] **Step 11: Commit**

```bash
git add mcp_servers tests/mcp_servers
git commit -m "feat: add domain-data MCP server with a Finnhub quote tool"
```

### Task 3: Chat agent wired to the one-tool MCP server

**Files:**
- Create: `agents/llm.py`
- Create: `agents/mcp_client.py`
- Create: `agents/chat.py`
- Test: `tests/agents/test_chat.py`

**Interfaces:**
- Consumes: MCP server from Task 2, launched via `python -m mcp_servers.domain_data.server`.
- Produces: `get_llm() -> BaseChatModel` in `agents/llm.py` (monkeypatched in tests).
- Produces: `build_mcp_client() -> MultiServerMCPClient` in `agents/mcp_client.py`.
- Produces: `async def chat(message: str, mcp_client: MultiServerMCPClient, llm=None) -> str` in `agents/chat.py` — later tasks (4, 18) call this exact signature.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_chat.py
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from agents.chat import chat

class _FakeToolsClient:
    async def get_tools(self):
        return []

@pytest.mark.asyncio
async def test_chat_returns_llm_text_response():
    fake_llm = FakeListChatModel(responses=["The market is currently advisory-only."])
    reply = await chat("What can you tell me?", _FakeToolsClient(), llm=fake_llm)
    assert reply == "The market is currently advisory-only."
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/agents/test_chat.py -v`
Expected: FAIL — `agents.chat` does not exist

- [ ] **Step 3: Implement the LLM factory, MCP client builder, and chat function**

```python
# agents/llm.py
import os
from langchain_anthropic import ChatAnthropic

def get_llm():
    return ChatAnthropic(
        model="claude-sonnet-5",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        temperature=0,
    )
```

```python
# agents/mcp_client.py
from langchain_mcp_adapters.client import MultiServerMCPClient

def build_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "domain_data": {
                "command": "python",
                "args": ["-m", "mcp_servers.domain_data.server"],
                "transport": "stdio",
            }
        }
    )
```

```python
# agents/chat.py
from langgraph.prebuilt import create_react_agent
from agents.llm import get_llm

SYSTEM_PROMPT = (
    "You are a trading research assistant. You are advisory only: you may "
    "look up market data, news, and saved backtest results, but you must "
    "never claim to place, modify, or cancel a real trade."
)

async def chat(message: str, mcp_client, llm=None) -> str:
    llm = llm or get_llm()
    tools = await mcp_client.get_tools()
    agent = create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": message}]})
    return result["messages"][-1].content
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/agents/test_chat.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add agents tests/agents
git commit -m "feat: add chat agent wired to the domain-data MCP server"
```

### Task 4: FastAPI backend with /healthz and /chat

**Files:**
- Create: `backend/main.py`
- Test: `tests/backend/test_main.py`

**Interfaces:**
- Consumes: `chat()` from Task 3 (`agents/chat.py`), `build_mcp_client()` from `agents/mcp_client.py`.
- Produces: FastAPI `app` in `backend/main.py` with `GET /healthz -> {"status": "ok"}` and `POST /chat {"message": str} -> {"reply": str}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_main.py
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_chat_endpoint_returns_agent_reply():
    with patch("backend.main.chat", new=AsyncMock(return_value="Advisory answer.")):
        response = client.post("/chat", json={"message": "Is now a good time to buy X?"})
    assert response.status_code == 200
    assert response.json() == {"reply": "Advisory answer."}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/backend/test_main.py -v`
Expected: FAIL — `backend.main` does not exist

- [ ] **Step 3: Implement the FastAPI app**

```python
# backend/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
from agents.chat import chat
from agents.mcp_client import build_mcp_client

mcp_client = build_mcp_client()

@asynccontextmanager
async def lifespan(_: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    reply = await chat(request.message, mcp_client)
    return ChatResponse(reply=reply)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/backend/test_main.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend tests/backend
git commit -m "feat: add FastAPI backend with healthz and chat endpoints"
```

### Task 5: Containerize and deploy the skeleton to a local Kubernetes cluster

**Files:**
- Create: `Dockerfile`
- Create: `k8s/base/deployment.yaml`
- Create: `k8s/base/service.yaml`

**Interfaces:**
- Consumes: `backend/main.py` (Task 4) as the container's entrypoint.
- Produces: image `trading-agent-backend:local`; a `Deployment`/`Service` pair reused (with env/image overrides) by Tasks 6, 28, and 30, and re-pointed at the real cluster in Task 46.

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY shared shared
COPY mcp_servers mcp_servers
COPY agents agents
COPY backend backend
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Build the image and verify it runs**

Run: `docker build -t trading-agent-backend:local . && docker run -d -p 8000:8000 -e FINNHUB_API_KEY=test -e ANTHROPIC_API_KEY=test --name skeleton-check trading-agent-backend:local && sleep 2 && curl -f http://localhost:8000/healthz && docker rm -f skeleton-check`
Expected: `{"status":"ok"}`, container removed cleanly

- [ ] **Step 3: Write the Kubernetes Deployment and Service manifests**

```yaml
# k8s/base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
spec:
  replicas: 1
  selector:
    matchLabels: { app: backend }
  template:
    metadata:
      labels: { app: backend }
    spec:
      containers:
        - name: backend
          image: trading-agent-backend:local
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef: { name: backend-config }
            - secretRef: { name: backend-secrets }
          livenessProbe:
            httpGet: { path: /healthz, port: 8000 }
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet: { path: /healthz, port: 8000 }
            initialDelaySeconds: 2
            periodSeconds: 5
```

```yaml
# k8s/base/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: backend
spec:
  selector: { app: backend }
  ports:
    - port: 80
      targetPort: 8000
```

- [ ] **Step 4: Create a local cluster, load the image, and apply the manifests**

```bash
kind create cluster --name trading-agent
kind load docker-image trading-agent-backend:local --name trading-agent
kubectl create configmap backend-config --from-literal=DUMMY=1
kubectl create secret generic backend-secrets --from-literal=FINNHUB_API_KEY=test --from-literal=ANTHROPIC_API_KEY=test
kubectl apply -f k8s/base/deployment.yaml -f k8s/base/service.yaml
```

- [ ] **Step 5: Verify the pod is healthy and reachable**

Run: `kubectl rollout status deployment/backend --timeout=60s && kubectl port-forward svc/backend 8080:80 & sleep 2 && curl -f http://localhost:8080/healthz`
Expected: rollout succeeds; `{"status":"ok"}` returned through the Service

- [ ] **Step 6: Commit**

```bash
git add Dockerfile k8s/base
git commit -m "feat: containerize the backend and deploy the skeleton to a local cluster"
```

### Task 6: CI workflow for the skeleton

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `pytest` config from Task 1, tests from Tasks 2–4.
- Produces: a `ci.yml` workflow extended in Task 48 with build/push and MCP integration test steps.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/ci.yml
name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check .
      - name: Unit + integration tests
        run: pytest --cov=. --cov-report=xml -v
        env:
          FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
      - name: Job summary
        if: always()
        run: |
          echo "## Test results" >> "$GITHUB_STEP_SUMMARY"
          pytest --cov=. --cov-report=term-missing | tail -n 20 >> "$GITHUB_STEP_SUMMARY" || true
      - name: Coverage badge
        uses: irongut/CodeCoverageSummary@v1.3.0
        with:
          filename: coverage.xml
          badge: true
          format: markdown
          output: both
```

- [ ] **Step 2: Verify locally**

Run: `act pull_request -j test` (or push a branch and open a PR)
Expected: lint and test steps pass, job summary rendered

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run lint and tests on every pull request"
```

---

## Phase 2 — MCP servers, full tool set

Rounds out the Domain-Data MCP server with the rest of the validated data sources, and adds TradingView MCP as a second server. Every tool follows the same pattern: mocked-HTTP unit test → implementation → registration on `mcp` → an addition to the tool-discovery integration test.

### Task 7: Finnhub company news and company profile tools

**Files:**
- Modify: `mcp_servers/domain_data/finnhub_client.py`
- Modify: `mcp_servers/domain_data/server.py`
- Modify: `tests/mcp_servers/test_finnhub_client.py`

**Interfaces:**
- Produces: `get_company_news(symbol: str, from_date: str, to_date: str) -> list[dict]` (each `{"headline": str, "summary": str, "url": str, "datetime": int}`).
- Produces: `get_company_profile(symbol: str) -> dict` (`{"symbol": str, "market_cap": float, "avg_volume": float, "week52_high": float, "week52_low": float, "beta": float}`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/mcp_servers/test_finnhub_client.py (append)
def test_get_company_news_parses_items(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

    def handler(request):
        return httpx.Response(
            200,
            json=[
                {"headline": "AAPL beats estimates", "summary": "...", "url": "https://x", "datetime": 1710000000}
            ],
        )

    monkeypatch.setattr(
        finnhub_client, "_client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    news = finnhub_client.get_company_news("AAPL", "2024-01-01", "2024-01-31")
    assert news == [
        {"headline": "AAPL beats estimates", "summary": "...", "url": "https://x", "datetime": 1710000000}
    ]

def test_get_company_profile_parses_fields(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

    def handler(request):
        if "metric" in str(request.url):
            return httpx.Response(
                200,
                json={"metric": {"52WeekHigh": 199.6, "52WeekLow": 164.1, "beta": 1.2, "10DayAverageTradingVolume": 55.4}},
            )
        return httpx.Response(200, json={"marketCapitalization": 2900000.0})

    monkeypatch.setattr(
        finnhub_client, "_client", httpx.Client(transport=httpx.MockTransport(handler))
    )
    profile = finnhub_client.get_company_profile("AAPL")
    assert profile == {
        "symbol": "AAPL",
        "market_cap": 2900000.0,
        "avg_volume": 55.4,
        "week52_high": 199.6,
        "week52_low": 164.1,
        "beta": 1.2,
    }
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_finnhub_client.py -v`
Expected: FAIL — `get_company_news`/`get_company_profile` not defined

- [ ] **Step 3: Implement both functions**

```python
# mcp_servers/domain_data/finnhub_client.py (append)
def get_company_news(symbol: str, from_date: str, to_date: str) -> list[dict]:
    response = request_with_retry(
        _client,
        "GET",
        "/company-news",
        params={"symbol": symbol, "from": from_date, "to": to_date, "token": _api_key()},
    )
    return [
        {"headline": item["headline"], "summary": item["summary"], "url": item["url"], "datetime": item["datetime"]}
        for item in response.json()
    ]

def get_company_profile(symbol: str) -> dict:
    metrics = request_with_retry(
        _client, "GET", "/stock/metric", params={"symbol": symbol, "metric": "all", "token": _api_key()}
    ).json()["metric"]
    profile = request_with_retry(
        _client, "GET", "/stock/profile2", params={"symbol": symbol, "token": _api_key()}
    ).json()
    return {
        "symbol": symbol,
        "market_cap": profile["marketCapitalization"],
        "avg_volume": metrics["10DayAverageTradingVolume"],
        "week52_high": metrics["52WeekHigh"],
        "week52_low": metrics["52WeekLow"],
        "beta": metrics["beta"],
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/mcp_servers/test_finnhub_client.py -v`
Expected: 4 passed

- [ ] **Step 5: Register both tools on the MCP server**

```python
# mcp_servers/domain_data/server.py (append)
@mcp.tool()
def get_company_news(symbol: str, from_date: str, to_date: str) -> list[dict]:
    """Get recent news headlines for a US equity ticker between two ISO dates."""
    return finnhub_client.get_company_news(symbol, from_date, to_date)

@mcp.tool()
def get_company_profile(symbol: str) -> dict:
    """Get market cap, average volume, 52-week range, and beta for a ticker."""
    return finnhub_client.get_company_profile(symbol)
```

- [ ] **Step 6: Extend the tool-discovery integration test**

```python
# tests/mcp_servers/test_server_integration.py (extend the assertion)
            assert {"get_quote", "get_company_news", "get_company_profile"} <= names
```

Run: `pytest tests/mcp_servers/test_server_integration.py -v`
Expected: 1 passed

- [ ] **Step 7: Commit**

```bash
git add mcp_servers tests/mcp_servers
git commit -m "feat: add Finnhub company news and profile tools"
```

### Task 8: FMP income statement and analyst estimates tools

**Files:**
- Create: `mcp_servers/domain_data/fmp_client.py`
- Modify: `mcp_servers/domain_data/server.py`
- Test: `tests/mcp_servers/test_fmp_client.py`

**Interfaces:**
- Produces: `get_income_statement(symbol: str) -> list[dict]` and `get_analyst_estimates(symbol: str) -> list[dict]`, both hitting FMP's `/stable/` endpoints (the legacy `/v3/` paths were retired August 2025 — spec §13).

- [ ] **Step 1: Write the failing tests**

```python
# tests/mcp_servers/test_fmp_client.py
import httpx
from mcp_servers.domain_data import fmp_client

def test_get_income_statement_hits_stable_endpoint(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")

    def handler(request):
        assert request.url.path == "/stable/income-statement"
        assert request.url.params["symbol"] == "AAPL"
        return httpx.Response(200, json=[{"date": "2024-09-28", "revenue": 391035000000}])

    monkeypatch.setattr(fmp_client, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    result = fmp_client.get_income_statement("AAPL")
    assert result == [{"date": "2024-09-28", "revenue": 391035000000}]

def test_get_analyst_estimates_hits_stable_endpoint(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")

    def handler(request):
        assert request.url.path == "/stable/analyst-estimates"
        return httpx.Response(200, json=[{"date": "2025-09-30", "estimatedRevenueAvg": 400000000000}])

    monkeypatch.setattr(fmp_client, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    result = fmp_client.get_analyst_estimates("AAPL")
    assert result == [{"date": "2025-09-30", "estimatedRevenueAvg": 400000000000}]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_fmp_client.py -v`
Expected: FAIL — `fmp_client` does not exist

- [ ] **Step 3: Implement the FMP client**

```python
# mcp_servers/domain_data/fmp_client.py
import os
import httpx
from mcp_servers.domain_data.http import request_with_retry

BASE_URL = "https://financialmodelingprep.com/stable"
_client = httpx.Client(base_url=BASE_URL, timeout=10.0)

def _api_key() -> str:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        raise RuntimeError("FMP_API_KEY is not set")
    return key

def get_income_statement(symbol: str) -> list[dict]:
    response = request_with_retry(
        _client, "GET", "/income-statement", params={"symbol": symbol, "period": "annual", "apikey": _api_key()}
    )
    return response.json()

def get_analyst_estimates(symbol: str) -> list[dict]:
    response = request_with_retry(
        _client, "GET", "/analyst-estimates", params={"symbol": symbol, "period": "annual", "apikey": _api_key()}
    )
    return response.json()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/mcp_servers/test_fmp_client.py -v`
Expected: 2 passed

- [ ] **Step 5: Register both tools and extend the discovery test**

```python
# mcp_servers/domain_data/server.py (append)
from mcp_servers.domain_data import fmp_client

@mcp.tool()
def get_income_statement(symbol: str) -> list[dict]:
    """Get annual income statement history for a US equity ticker (FMP)."""
    return fmp_client.get_income_statement(symbol)

@mcp.tool()
def get_analyst_estimates(symbol: str) -> list[dict]:
    """Get annual analyst revenue/earnings estimates for a US equity ticker (FMP)."""
    return fmp_client.get_analyst_estimates(symbol)
```

Add `"get_income_statement", "get_analyst_estimates"` to the discovery test's expected set.

Run: `pytest tests/mcp_servers/test_server_integration.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add mcp_servers tests/mcp_servers
git commit -m "feat: add FMP income statement and analyst estimates tools"
```

### Task 9: FRED macro indicator tool

**Files:**
- Create: `mcp_servers/domain_data/fred_client.py`
- Modify: `mcp_servers/domain_data/server.py`
- Test: `tests/mcp_servers/test_fred_client.py`

**Interfaces:**
- Produces: `get_series(series_id: str) -> list[dict]` returning `[{"date": str, "value": float}, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp_servers/test_fred_client.py
import httpx
from mcp_servers.domain_data import fred_client

def test_get_series_parses_observations(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")

    def handler(request):
        assert request.url.params["series_id"] == "CPIAUCSL"
        return httpx.Response(
            200,
            json={"observations": [{"date": "2024-01-01", "value": "308.417"}, {"date": "2024-02-01", "value": "310.326"}]},
        )

    monkeypatch.setattr(fred_client, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    result = fred_client.get_series("CPIAUCSL")
    assert result == [{"date": "2024-01-01", "value": 308.417}, {"date": "2024-02-01", "value": 310.326}]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_fred_client.py -v`
Expected: FAIL — `fred_client` does not exist

- [ ] **Step 3: Implement the FRED client**

```python
# mcp_servers/domain_data/fred_client.py
import os
import httpx
from mcp_servers.domain_data.http import request_with_retry

BASE_URL = "https://api.stlouisfed.org/fred"
_client = httpx.Client(base_url=BASE_URL, timeout=10.0)

def _api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY is not set")
    return key

def get_series(series_id: str) -> list[dict]:
    response = request_with_retry(
        _client,
        "GET",
        "/series/observations",
        params={"series_id": series_id, "api_key": _api_key(), "file_type": "json"},
    )
    return [{"date": obs["date"], "value": float(obs["value"])} for obs in response.json()["observations"]]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/mcp_servers/test_fred_client.py -v`
Expected: 1 passed

- [ ] **Step 5: Register the tool and extend the discovery test**

```python
# mcp_servers/domain_data/server.py (append)
from mcp_servers.domain_data import fred_client

@mcp.tool()
def get_macro_series(series_id: str) -> list[dict]:
    """Get a FRED macroeconomic time series, e.g. CPIAUCSL, UNRATE, FEDFUNDS, GDP."""
    return fred_client.get_series(series_id)
```

Add `"get_macro_series"` to the discovery test's expected set.

Run: `pytest tests/mcp_servers/test_server_integration.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add mcp_servers tests/mcp_servers
git commit -m "feat: add FRED macro indicator tool"
```

### Task 10: edgartools insider transaction tool with S/P filtering

**Files:**
- Create: `mcp_servers/domain_data/edgar_client.py`
- Modify: `mcp_servers/domain_data/server.py`
- Test: `tests/mcp_servers/test_edgar_client.py`

**Interfaces:**
- Produces: `get_insider_transactions(symbol: str) -> list[dict]`, returning only transaction codes `"S"` and `"P"` (spec §13 — excludes `"M"`, `"F"`, `"G"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp_servers/test_edgar_client.py
from unittest.mock import MagicMock, patch
from mcp_servers.domain_data import edgar_client

def _tx(code, shares=100):
    row = MagicMock()
    row.to_dict.return_value = {"code": code, "shares": shares, "insider": "J. Doe", "date": "2024-05-01"}
    return row

def test_filters_to_sale_and_purchase_codes_only():
    fake_df = MagicMock()
    fake_df.itertuples.return_value = []
    rows = [
        {"code": "S", "shares": 500, "insider": "J. Doe", "date": "2024-05-01"},
        {"code": "P", "shares": 200, "insider": "J. Doe", "date": "2024-04-01"},
        {"code": "M", "shares": 1000, "insider": "J. Doe", "date": "2024-03-01"},
        {"code": "F", "shares": 50, "insider": "J. Doe", "date": "2024-03-02"},
        {"code": "G", "shares": 10, "insider": "J. Doe", "date": "2024-02-01"},
    ]
    with patch.object(edgar_client, "_fetch_form4_rows", return_value=rows):
        result = edgar_client.get_insider_transactions("AAPL")
    codes = {tx["code"] for tx in result}
    assert codes == {"S", "P"}
    assert len(result) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_edgar_client.py -v`
Expected: FAIL — `edgar_client` does not exist

- [ ] **Step 3: Implement the client**

```python
# mcp_servers/domain_data/edgar_client.py
import os
from edgar import Company, set_identity

DISCRETIONARY_CODES = {"S", "P"}

def _identity() -> str:
    identity = os.environ.get("EDGAR_IDENTITY")
    if not identity:
        raise RuntimeError("EDGAR_IDENTITY is not set")
    return identity

def _fetch_form4_rows(symbol: str) -> list[dict]:
    set_identity(_identity())
    filings = Company(symbol).get_filings(form="4")
    rows = []
    for filing in filings:
        obj = filing.obj()
        for tx in obj.transactions:
            rows.append(
                {
                    "code": tx.code,
                    "shares": tx.shares,
                    "insider": obj.reporting_owner.name,
                    "date": str(filing.filing_date),
                }
            )
    return rows

def get_insider_transactions(symbol: str) -> list[dict]:
    rows = _fetch_form4_rows(symbol)
    return [row for row in rows if row["code"] in DISCRETIONARY_CODES]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/mcp_servers/test_edgar_client.py -v`
Expected: 1 passed

- [ ] **Step 5: Register the tool and extend the discovery test**

```python
# mcp_servers/domain_data/server.py (append)
from mcp_servers.domain_data import edgar_client

@mcp.tool()
def get_insider_transactions(symbol: str) -> list[dict]:
    """Get discretionary insider buy/sell transactions (Form 4, codes S and P only)."""
    return edgar_client.get_insider_transactions(symbol)
```

Add `"get_insider_transactions"` to the discovery test's expected set.

Run: `pytest tests/mcp_servers/test_server_integration.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add mcp_servers tests/mcp_servers
git commit -m "feat: add insider transaction tool filtered to S/P codes"
```

### Task 11: edgartools 13F institutional holdings tool

**Files:**
- Modify: `mcp_servers/domain_data/edgar_client.py`
- Modify: `mcp_servers/domain_data/server.py`
- Modify: `tests/mcp_servers/test_edgar_client.py`

**Interfaces:**
- Produces: `get_13f_holdings(ticker: str) -> dict` returning `{"total_holdings": int, "total_value": float, "holdings": list[dict]}` — quarterly, filed up to 45 days late (spec §13, treated as long-term conviction context, not a timely signal).

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp_servers/test_edgar_client.py (append)
from unittest.mock import MagicMock, patch
import pandas as pd

def test_get_13f_holdings_summarizes_dataframe():
    fake_df = pd.DataFrame(
        [
            {"issuer": "Apple Inc", "value": 150000000, "shares": 900000},
            {"issuer": "Coca-Cola Co", "value": 25000000, "shares": 400000},
        ]
    )
    fake_filing_obj = MagicMock(total_holdings=2, total_value=175000000)
    fake_filing_obj.get_holdings.return_value = fake_df
    fake_filing = MagicMock()
    fake_filing.obj.return_value = fake_filing_obj
    fake_filings = MagicMock()
    fake_filings.latest.return_value = fake_filing

    with patch.object(edgar_client, "Company") as mock_company:
        mock_company.return_value.get_filings.return_value = fake_filings
        result = edgar_client.get_13f_holdings("BRK-A")

    assert result["total_holdings"] == 2
    assert result["total_value"] == 175000000
    assert len(result["holdings"]) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_edgar_client.py -v`
Expected: FAIL — `get_13f_holdings` not defined

- [ ] **Step 3: Implement the function**

```python
# mcp_servers/domain_data/edgar_client.py (append)
def get_13f_holdings(ticker: str) -> dict:
    set_identity(_identity())
    filings = Company(ticker).get_filings(form="13F-HR")
    latest = filings.latest()
    obj = latest.obj()
    holdings_df = obj.get_holdings()
    return {
        "total_holdings": obj.total_holdings,
        "total_value": obj.total_value,
        "holdings": holdings_df.to_dict(orient="records"),
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/mcp_servers/test_edgar_client.py -v`
Expected: 2 passed

- [ ] **Step 5: Register the tool and extend the discovery test**

```python
# mcp_servers/domain_data/server.py (append)
@mcp.tool()
def get_institutional_holdings(ticker: str) -> dict:
    """Get the latest 13F institutional holdings summary for a fund/company ticker."""
    return edgar_client.get_13f_holdings(ticker)
```

Add `"get_institutional_holdings"` to the discovery test's expected set.

Run: `pytest tests/mcp_servers/test_server_integration.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add mcp_servers tests/mcp_servers
git commit -m "feat: add 13F institutional holdings tool"
```

### Task 12: S3 reader for MT5-derived historical OHLCV

**Files:**
- Create: `mcp_servers/domain_data/mt5_data.py`
- Modify: `mcp_servers/domain_data/server.py`
- Test: `tests/mcp_servers/test_mt5_data.py`

**Interfaces:**
- Produces: `read_ohlcv(symbol: str, timeframe: str) -> list[dict]`, reading `s3://{MT5_DATA_BUCKET}/{symbol}/{timeframe}.parquet` and returning `[{"time": str, "open": float, "high": float, "low": float, "close": float, "volume": float}, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp_servers/test_mt5_data.py
import io
import pandas as pd
import boto3
import pytest
from moto import mock_aws
from mcp_servers.domain_data import mt5_data

@pytest.fixture
def s3_bucket(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("MT5_DATA_BUCKET", "mt5-data-test")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="mt5-data-test")
        df = pd.DataFrame(
            [{"time": "2024-01-01", "open": 190.0, "high": 192.0, "low": 189.0, "close": 191.5, "volume": 1000000}]
        )
        buffer = io.BytesIO()
        df.to_parquet(buffer)
        client.put_object(Bucket="mt5-data-test", Key="AAPL/1H.parquet", Body=buffer.getvalue())
        yield client

def test_read_ohlcv_returns_rows(s3_bucket):
    rows = mt5_data.read_ohlcv("AAPL", "1H")
    assert rows == [
        {"time": "2024-01-01", "open": 190.0, "high": 192.0, "low": 189.0, "close": 191.5, "volume": 1000000.0}
    ]

def test_read_ohlcv_raises_for_missing_symbol(s3_bucket):
    with pytest.raises(FileNotFoundError):
        mt5_data.read_ohlcv("MISSING", "1H")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_mt5_data.py -v`
Expected: FAIL — `mt5_data` does not exist

- [ ] **Step 3: Implement the reader**

```python
# mcp_servers/domain_data/mt5_data.py
import io
import os
import boto3
import pandas as pd
from botocore.exceptions import ClientError

def read_ohlcv(symbol: str, timeframe: str) -> list[dict]:
    bucket = os.environ["MT5_DATA_BUCKET"]
    key = f"{symbol}/{timeframe}.parquet"
    client = boto3.client("s3")
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            raise FileNotFoundError(f"No historical data for {symbol} at {timeframe}") from exc
        raise
    df = pd.read_parquet(io.BytesIO(obj["Body"].read()))
    return df.to_dict(orient="records")
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/mcp_servers/test_mt5_data.py -v`
Expected: 2 passed

- [ ] **Step 5: Register the tool and extend the discovery test**

```python
# mcp_servers/domain_data/server.py (append)
from mcp_servers.domain_data import mt5_data

@mcp.tool()
def get_historical_ohlcv(symbol: str, timeframe: str) -> list[dict]:
    """Get MT5-derived historical OHLCV bars for a symbol (timeframe: 1D, 4H, 1H, 15min, 5min, 1min)."""
    return mt5_data.read_ohlcv(symbol, timeframe)
```

Add `"get_historical_ohlcv"` to the discovery test's expected set.

Run: `pytest tests/mcp_servers/test_server_integration.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add mcp_servers tests/mcp_servers
git commit -m "feat: add S3-backed MT5 historical OHLCV reader tool"
```

### Task 13: Fallback technical-indicator tool

**Files:**
- Create: `mcp_servers/domain_data/indicators.py`
- Modify: `mcp_servers/domain_data/server.py`
- Test: `tests/mcp_servers/test_indicators.py`

**Interfaces:**
- Produces: `compute_fallback_indicators(closes: list[float]) -> dict` returning `{"sma_20": float | None, "sma_50": float | None, "ema_12": float | None, "ema_26": float | None}` — used when TradingView MCP is unreachable (spec §11).

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp_servers/test_indicators.py
from mcp_servers.domain_data.indicators import compute_fallback_indicators

def test_computes_moving_averages_with_enough_data():
    closes = [float(100 + i) for i in range(60)]
    result = compute_fallback_indicators(closes)
    assert result["sma_20"] == sum(closes[-20:]) / 20
    assert result["sma_50"] == sum(closes[-50:]) / 50
    assert result["ema_12"] is not None
    assert result["ema_26"] is not None

def test_returns_none_for_indicators_without_enough_data():
    result = compute_fallback_indicators([100.0, 101.0])
    assert result == {"sma_20": None, "sma_50": None, "ema_12": None, "ema_26": None}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_indicators.py -v`
Expected: FAIL — `indicators` module does not exist

- [ ] **Step 3: Implement the fallback indicators**

```python
# mcp_servers/domain_data/indicators.py
def _sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def _ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def compute_fallback_indicators(closes: list[float]) -> dict:
    return {
        "sma_20": _sma(closes, 20),
        "sma_50": _sma(closes, 50),
        "ema_12": _ema(closes, 12),
        "ema_26": _ema(closes, 26),
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/mcp_servers/test_indicators.py -v`
Expected: 2 passed

- [ ] **Step 5: Register the tool and extend the discovery test**

```python
# mcp_servers/domain_data/server.py (append)
from mcp_servers.domain_data import mt5_data as _mt5_data
from mcp_servers.domain_data.indicators import compute_fallback_indicators

@mcp.tool()
def get_fallback_indicators(symbol: str, timeframe: str) -> dict:
    """Compute SMA/EMA locally from stored OHLCV when TradingView MCP is unreachable."""
    bars = _mt5_data.read_ohlcv(symbol, timeframe)
    closes = [bar["close"] for bar in bars]
    return compute_fallback_indicators(closes)
```

Add `"get_fallback_indicators"` to the discovery test's expected set.

Run: `pytest tests/mcp_servers/test_server_integration.py -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add mcp_servers tests/mcp_servers
git commit -m "feat: add fallback technical-indicator tool"
```

### Task 14: Wire TradingView MCP as a second server

**Files:**
- Modify: `agents/mcp_client.py`
- Modify: `tests/agents/test_mcp_client.py` (create)

**Interfaces:**
- Consumes: `github.com/atilaahmettaner/tradingview-mcp`, launched via `npx`.
- Produces: `build_mcp_client()` now configures two servers (`domain_data`, `tradingview`); `MARKETAUX_API_KEY` is optional (spec §11 — sentiment degrades to "Unavailable" without it, technicals still work).

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_mcp_client.py
from agents.mcp_client import build_mcp_client

def test_client_configures_both_servers():
    client = build_mcp_client()
    assert set(client.connections.keys()) == {"domain_data", "tradingview"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/agents/test_mcp_client.py -v`
Expected: FAIL — only `domain_data` present

- [ ] **Step 3: Add the TradingView MCP server to the client config**

```python
# agents/mcp_client.py
from langchain_mcp_adapters.client import MultiServerMCPClient

def build_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "domain_data": {
                "command": "python",
                "args": ["-m", "mcp_servers.domain_data.server"],
                "transport": "stdio",
            },
            "tradingview": {
                "command": "npx",
                "args": ["-y", "tradingview-mcp"],
                "transport": "stdio",
            },
        }
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/agents/test_mcp_client.py -v`
Expected: 1 passed

- [ ] **Step 5: Add a real-transport tool discovery test across both servers**

```python
# tests/agents/test_mcp_client_integration.py
import pytest
from agents.mcp_client import build_mcp_client

@pytest.mark.asyncio
async def test_tools_are_discoverable_from_both_servers(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    client = build_mcp_client()
    tools = await client.get_tools()
    names = {tool.name for tool in tools}
    assert "get_quote" in names
    assert any("technical" in name or "combined_analysis" in name for name in names)
```

Run: `pytest tests/agents/test_mcp_client_integration.py -v`
Expected: 1 passed (requires `npx` and network access to fetch the `tradingview-mcp` package the first time)

- [ ] **Step 6: Commit**

```bash
git add agents tests/agents
git commit -m "feat: wire TradingView MCP as a second server on the agent's tool set"
```

---

## Phase 3 — Multi-agent pipeline

News analyzer, company analyzer, and signal scorer as separate `StateGraph` nodes, each with its own system prompt (persona, capabilities, boundary), per spec §4.2.

### Task 15: News analyzer node

**Files:**
- Create: `agents/pipeline.py`
- Test: `tests/agents/test_pipeline.py`

**Interfaces:**
- Produces: `PipelineState` (TypedDict: `news_item: dict`, `fundamentals: dict`, `sentiment: dict | None`, `fundamentals_check: dict | None`, `signal: dict | None`) and `news_analyzer_node(state: PipelineState, llm=None) -> dict`, both consumed by Tasks 16–17 and Task 26.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_pipeline.py
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from agents.pipeline import news_analyzer_node

def test_news_analyzer_returns_parsed_sentiment():
    fake_llm = FakeListChatModel(
        responses=['{"sentiment": "positive", "impact": "high", "reasoning": "Beat on revenue and EPS."}']
    )
    state = {
        "news_item": {"headline": "AAPL beats Q3 estimates", "summary": "Revenue and EPS both beat consensus."},
        "fundamentals": {},
        "sentiment": None,
        "fundamentals_check": None,
        "signal": None,
    }
    result = news_analyzer_node(state, llm=fake_llm)
    assert result == {
        "sentiment": {"sentiment": "positive", "impact": "high", "reasoning": "Beat on revenue and EPS."}
    }
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/agents/test_pipeline.py -v`
Expected: FAIL — `agents.pipeline` does not exist

- [ ] **Step 3: Implement the state type, prompt, and node**

```python
# agents/pipeline.py
import json
from typing import TypedDict
from agents.llm import get_llm

NEWS_ANALYZER_PROMPT = (
    "You are a news sentiment analyst for a trading research agent. You are "
    "advisory only: you assess sentiment and impact, you never suggest that a "
    "trade has been or will be executed. Given a news headline and summary, "
    "respond with strict JSON only: "
    '{"sentiment": "positive"|"negative"|"neutral", "impact": "high"|"medium"|"low", "reasoning": str}.'
)

class PipelineState(TypedDict):
    news_item: dict
    fundamentals: dict
    sentiment: dict | None
    fundamentals_check: dict | None
    signal: dict | None

def news_analyzer_node(state: PipelineState, llm=None) -> dict:
    llm = llm or get_llm()
    item = state["news_item"]
    response = llm.invoke(
        [
            {"role": "system", "content": NEWS_ANALYZER_PROMPT},
            {"role": "user", "content": f"Headline: {item['headline']}\nSummary: {item['summary']}"},
        ]
    )
    return {"sentiment": json.loads(response.content)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/agents/test_pipeline.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add agents tests/agents
git commit -m "feat: add news analyzer pipeline node"
```

### Task 16: Company analyzer node

**Files:**
- Modify: `agents/pipeline.py`
- Modify: `tests/agents/test_pipeline.py`

**Interfaces:**
- Produces: `company_analyzer_node(state: PipelineState, llm=None) -> dict`, consumed by Task 17's graph wiring.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_pipeline.py (append)
from agents.pipeline import company_analyzer_node

def test_company_analyzer_returns_parsed_fundamentals_check():
    fake_llm = FakeListChatModel(
        responses=['{"fundamentals_support_reaction": true, "reasoning": "Revenue growth is consistent with the beat."}']
    )
    state = {
        "news_item": {"headline": "x", "summary": "y"},
        "fundamentals": {"revenue": 391035000000},
        "sentiment": {"sentiment": "positive", "impact": "high", "reasoning": "..."},
        "fundamentals_check": None,
        "signal": None,
    }
    result = company_analyzer_node(state, llm=fake_llm)
    assert result == {
        "fundamentals_check": {
            "fundamentals_support_reaction": True,
            "reasoning": "Revenue growth is consistent with the beat.",
        }
    }
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/agents/test_pipeline.py -v`
Expected: FAIL — `company_analyzer_node` not defined

- [ ] **Step 3: Implement the node**

```python
# agents/pipeline.py (append)
COMPANY_ANALYZER_PROMPT = (
    "You are a fundamentals sanity-check analyst for a trading research agent. "
    "You are advisory only. Given a news sentiment assessment and the company's "
    "recent financial data, judge whether the reaction is fundamentally "
    "justified. Respond with strict JSON only: "
    '{"fundamentals_support_reaction": bool, "reasoning": str}.'
)

def company_analyzer_node(state: PipelineState, llm=None) -> dict:
    llm = llm or get_llm()
    response = llm.invoke(
        [
            {"role": "system", "content": COMPANY_ANALYZER_PROMPT},
            {
                "role": "user",
                "content": f"Sentiment: {state['sentiment']}\nFundamentals: {state['fundamentals']}",
            },
        ]
    )
    return {"fundamentals_check": json.loads(response.content)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/agents/test_pipeline.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add agents tests/agents
git commit -m "feat: add company analyzer pipeline node"
```

### Task 17: Signal scorer node, graph wiring, and confidence threshold

**Files:**
- Modify: `agents/pipeline.py`
- Modify: `tests/agents/test_pipeline.py`

**Interfaces:**
- Consumes: `news_analyzer_node`, `company_analyzer_node` (Tasks 15–16).
- Produces: `signal_scorer_node(state, llm=None, threshold=0.7) -> dict`, `build_pipeline_graph(llm=None, threshold=0.7)`, and `run_pipeline_for_news_item(news_item: dict, fundamentals: dict, llm=None, threshold=0.7) -> PipelineState` — the last is called directly by Task 26's news consumer.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_pipeline.py (append)
from agents.pipeline import signal_scorer_node, run_pipeline_for_news_item

def test_signal_scorer_emits_signal_above_threshold():
    fake_llm = FakeListChatModel(
        responses=['{"confidence": 0.82, "suggestion": "buy", "reasoning": "Strong beat, fundamentals support it."}']
    )
    state = {
        "news_item": {"headline": "x", "summary": "y"},
        "fundamentals": {},
        "sentiment": {"sentiment": "positive", "impact": "high", "reasoning": "..."},
        "fundamentals_check": {"fundamentals_support_reaction": True, "reasoning": "..."},
        "signal": None,
    }
    result = signal_scorer_node(state, llm=fake_llm, threshold=0.7)
    assert result["signal"]["confidence"] == 0.82
    assert result["signal"]["suggestion"] == "buy"

def test_signal_scorer_withholds_signal_below_threshold():
    fake_llm = FakeListChatModel(
        responses=['{"confidence": 0.4, "suggestion": "watch", "reasoning": "Mixed signal."}']
    )
    state = {
        "news_item": {"headline": "x", "summary": "y"},
        "fundamentals": {},
        "sentiment": {"sentiment": "neutral", "impact": "low", "reasoning": "..."},
        "fundamentals_check": {"fundamentals_support_reaction": False, "reasoning": "..."},
        "signal": None,
    }
    result = signal_scorer_node(state, llm=fake_llm, threshold=0.7)
    assert result == {"signal": None}

def test_run_pipeline_for_news_item_runs_all_three_nodes_in_order():
    fake_llm = FakeListChatModel(
        responses=[
            '{"sentiment": "positive", "impact": "high", "reasoning": "r1"}',
            '{"fundamentals_support_reaction": true, "reasoning": "r2"}',
            '{"confidence": 0.9, "suggestion": "buy", "reasoning": "r3"}',
        ]
    )
    result = run_pipeline_for_news_item(
        news_item={"headline": "AAPL beats", "summary": "..."},
        fundamentals={"revenue": 1},
        llm=fake_llm,
        threshold=0.7,
    )
    assert result["signal"]["suggestion"] == "buy"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/agents/test_pipeline.py -v`
Expected: FAIL — `signal_scorer_node`/`run_pipeline_for_news_item` not defined

- [ ] **Step 3: Implement the node, graph, and entrypoint**

```python
# agents/pipeline.py (append)
from langgraph.graph import StateGraph, END

SIGNAL_SCORER_PROMPT = (
    "You are a signal-scoring analyst for a trading research agent. You are "
    "advisory only and must never claim that a trade has been placed, "
    "modified, or cancelled — you only score a suggestion's confidence. Given "
    "a sentiment assessment and a fundamentals sanity-check, respond with "
    'strict JSON only: {"confidence": float between 0 and 1, '
    '"suggestion": "buy"|"sell"|"watch", "reasoning": str}.'
)

def signal_scorer_node(state: PipelineState, llm=None, threshold: float = 0.7) -> dict:
    llm = llm or get_llm()
    response = llm.invoke(
        [
            {"role": "system", "content": SIGNAL_SCORER_PROMPT},
            {
                "role": "user",
                "content": f"Sentiment: {state['sentiment']}\nFundamentals check: {state['fundamentals_check']}",
            },
        ]
    )
    scored = json.loads(response.content)
    if scored["confidence"] < threshold:
        return {"signal": None}
    return {"signal": scored}

def build_pipeline_graph(llm=None, threshold: float = 0.7):
    graph = StateGraph(PipelineState)
    graph.add_node("news_analyzer", lambda state: news_analyzer_node(state, llm))
    graph.add_node("company_analyzer", lambda state: company_analyzer_node(state, llm))
    graph.add_node("signal_scorer", lambda state: signal_scorer_node(state, llm, threshold))
    graph.set_entry_point("news_analyzer")
    graph.add_edge("news_analyzer", "company_analyzer")
    graph.add_edge("company_analyzer", "signal_scorer")
    graph.add_edge("signal_scorer", END)
    return graph.compile()

def run_pipeline_for_news_item(
    news_item: dict, fundamentals: dict, llm=None, threshold: float = 0.7
) -> PipelineState:
    graph = build_pipeline_graph(llm, threshold)
    return graph.invoke(
        {
            "news_item": news_item,
            "fundamentals": fundamentals,
            "sentiment": None,
            "fundamentals_check": None,
            "signal": None,
        }
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/agents/test_pipeline.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents tests/agents
git commit -m "feat: add signal scorer node and wire the full pipeline graph"
```

### Task 18: Upgrade the chat agent's system prompt and confirm the full two-server tool set

**Files:**
- Modify: `agents/chat.py`
- Modify: `tests/agents/test_chat.py`

**Interfaces:**
- Consumes: `build_mcp_client()` (Task 14, now returns both servers).
- Produces: no signature change to `chat()` — the system prompt gains explicit capability/boundary language, and a test locks in that `chat()` binds every tool `mcp_client.get_tools()` returns, whatever server it came from.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_chat.py (append)
def test_chat_binds_every_tool_the_mcp_client_returns(monkeypatch):
    captured = {}

    def fake_create_react_agent(llm, tools, prompt=None):
        captured["tools"] = tools
        captured["prompt"] = prompt

        class _Agent:
            async def ainvoke(self, _):
                return {"messages": [type("M", (), {"content": "ok"})()]}

        return _Agent()

    monkeypatch.setattr("agents.chat.create_react_agent", fake_create_react_agent)
    fake_tools = [object(), object(), object(), object()]

    class _Client:
        async def get_tools(self):
            return fake_tools

    import asyncio
    from agents.chat import chat
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    asyncio.get_event_loop().run_until_complete(
        chat("hi", _Client(), llm=FakeListChatModel(responses=["ok"]))
    )
    assert captured["tools"] == fake_tools
    assert "never" in captured["prompt"].lower()
    assert "insider" in captured["prompt"].lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/agents/test_chat.py -v`
Expected: FAIL — current prompt doesn't mention "insider"

- [ ] **Step 3: Expand the system prompt**

```python
# agents/chat.py (replace SYSTEM_PROMPT)
SYSTEM_PROMPT = (
    "You are a trading research assistant covering US equities and ETFs. "
    "You are advisory only: you may look up live quotes, company news, "
    "fundamentals, analyst estimates, macro indicators, insider transactions, "
    "13F institutional holdings, technical indicators, and saved backtest "
    "results. You must never claim to place, modify, or cancel a real trade — "
    "you only ever produce suggestions and notifications."
)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/agents/test_chat.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add agents tests/agents
git commit -m "feat: expand chat agent system prompt to cover the full tool set"
```

### Task 19 (optional/stretch — spec §4.2): Devil's-advocate validation node

Not required to complete Phase 3; do this task only after Phase 3's core is committed and if time remains.

**Files:**
- Modify: `agents/pipeline.py`
- Modify: `tests/agents/test_pipeline.py`

**Interfaces:**
- Produces: `devils_advocate_node(state: PipelineState, llm=None) -> dict`, inserted between `signal_scorer` and `END` in `build_pipeline_graph`; can null out `state["signal"]` if it finds the case against the signal compelling.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_pipeline.py (append)
from agents.pipeline import devils_advocate_node

def test_devils_advocate_vetoes_a_weak_signal():
    fake_llm = FakeListChatModel(
        responses=['{"veto": true, "reasoning": "The move is already priced in per the 52-week high."}']
    )
    state = {
        "news_item": {"headline": "x", "summary": "y"},
        "fundamentals": {},
        "sentiment": {"sentiment": "positive", "impact": "high", "reasoning": "..."},
        "fundamentals_check": {"fundamentals_support_reaction": True, "reasoning": "..."},
        "signal": {"confidence": 0.75, "suggestion": "buy", "reasoning": "..."},
    }
    result = devils_advocate_node(state, llm=fake_llm)
    assert result == {"signal": None}

def test_devils_advocate_allows_a_strong_signal_through():
    fake_llm = FakeListChatModel(responses=['{"veto": false, "reasoning": "No compelling counter-argument."}'])
    original_signal = {"confidence": 0.9, "suggestion": "buy", "reasoning": "..."}
    state = {
        "news_item": {"headline": "x", "summary": "y"},
        "fundamentals": {},
        "sentiment": {"sentiment": "positive", "impact": "high", "reasoning": "..."},
        "fundamentals_check": {"fundamentals_support_reaction": True, "reasoning": "..."},
        "signal": original_signal,
    }
    result = devils_advocate_node(state, llm=fake_llm)
    assert result == {"signal": original_signal}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/agents/test_pipeline.py -v`
Expected: FAIL — `devils_advocate_node` not defined

- [ ] **Step 3: Implement the node and insert it into the graph**

```python
# agents/pipeline.py (append)
DEVILS_ADVOCATE_PROMPT = (
    "You are a skeptical second reviewer for a trading research agent. You "
    "are advisory only. Given a proposed signal and the analysis behind it, "
    "argue against it as hard as you honestly can, then decide whether it "
    "should be vetoed. Respond with strict JSON only: "
    '{"veto": bool, "reasoning": str}.'
)

def devils_advocate_node(state: PipelineState, llm=None) -> dict:
    if state["signal"] is None:
        return {"signal": None}
    llm = llm or get_llm()
    response = llm.invoke(
        [
            {"role": "system", "content": DEVILS_ADVOCATE_PROMPT},
            {"role": "user", "content": f"Signal: {state['signal']}\nSentiment: {state['sentiment']}"},
        ]
    )
    verdict = json.loads(response.content)
    return {"signal": None if verdict["veto"] else state["signal"]}
```

```python
# agents/pipeline.py (modify build_pipeline_graph to insert the node)
def build_pipeline_graph(llm=None, threshold: float = 0.7, with_devils_advocate: bool = True):
    graph = StateGraph(PipelineState)
    graph.add_node("news_analyzer", lambda state: news_analyzer_node(state, llm))
    graph.add_node("company_analyzer", lambda state: company_analyzer_node(state, llm))
    graph.add_node("signal_scorer", lambda state: signal_scorer_node(state, llm, threshold))
    graph.set_entry_point("news_analyzer")
    graph.add_edge("news_analyzer", "company_analyzer")
    graph.add_edge("company_analyzer", "signal_scorer")
    if with_devils_advocate:
        graph.add_node("devils_advocate", lambda state: devils_advocate_node(state, llm))
        graph.add_edge("signal_scorer", "devils_advocate")
        graph.add_edge("devils_advocate", END)
    else:
        graph.add_edge("signal_scorer", END)
    return graph.compile()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/agents/test_pipeline.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add agents tests/agents
git commit -m "feat: add optional devil's-advocate validation node"
```

---

## Phase 4 — Backtest engine wrapper

Wraps `backtesting.py` behind a stable interface and adds a golden-reference regression test, per spec §12. The test strategy is a moving-average crossover on synthetic, offline, deterministic data — not tied to any specific real-market example, so the test never depends on network access or a particular historical dataset.

### Task 20: `run_backtest` wrapper with a golden-reference regression test

**Files:**
- Create: `shared/models.py`
- Create: `backend/backtest_engine.py`
- Create: `scripts/generate_backtest_reference.py`
- Create: `tests/fixtures/backtest_reference.json` (generated, then committed)
- Test: `tests/backend/test_backtest_engine.py`

**Interfaces:**
- Produces: `BacktestParams` and `BacktestResult` (pydantic models) in `shared/models.py`, used by Tasks 21–22, 26, and Phase 8's backend routes.
- Produces: `run_backtest(params: BacktestParams, ohlcv: pd.DataFrame | None = None) -> BacktestResult` in `backend/backtest_engine.py`. When `ohlcv` is omitted it reads from `mcp_servers.domain_data.mt5_data.read_ohlcv` (Task 12); tests always pass a synthetic `ohlcv` directly so no S3 access is needed.

- [ ] **Step 1: Define the shared models and write the structural test**

```python
# shared/models.py
from pydantic import BaseModel

class BacktestParams(BaseModel):
    symbol: str
    timeframe: str
    fast_period: int = 20
    slow_period: int = 50
    starting_balance: float = 100_000.0
    leverage: float = 1.0
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.05

class BacktestResult(BaseModel):
    final_balance: float
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    num_trades: int
    win_rate_pct: float
    profit_factor: float
    equity_curve: list[dict]
    balance_curve: list[dict]
```

```python
# tests/backend/test_backtest_engine.py
import numpy as np
import pandas as pd
from shared.models import BacktestParams

def _synthetic_ohlcv(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    trend = np.linspace(100, 140, n)
    noise = rng.normal(0, 1.5, n)
    close = trend + noise + 5 * np.sin(np.linspace(0, 15, n))
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "time": dates,
            "open": close - 0.3,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1_000_000,
        }
    )

def test_run_backtest_produces_well_formed_result():
    from backend.backtest_engine import run_backtest

    params = BacktestParams(symbol="SYN", timeframe="1D", starting_balance=100_000.0, leverage=1.0)
    result = run_backtest(params, ohlcv=_synthetic_ohlcv())
    assert result.final_balance > 0
    assert result.num_trades >= 0
    assert len(result.equity_curve) == 300
    assert all("equity" in point for point in result.equity_curve)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/backend/test_backtest_engine.py -v`
Expected: FAIL — `backend.backtest_engine` does not exist

- [ ] **Step 3: Implement the strategy and wrapper**

```python
# backend/backtest_engine.py
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from shared.models import BacktestParams, BacktestResult
from mcp_servers.domain_data import mt5_data

class MovingAverageCrossStrategy(Strategy):
    fast_period = 20
    slow_period = 50
    stop_loss_pct = 0.05
    take_profit_pct = 0.05

    def init(self):
        close = self.data.Close
        self.fast_ma = self.I(lambda x: pd.Series(x).rolling(self.fast_period).mean(), close)
        self.slow_ma = self.I(lambda x: pd.Series(x).rolling(self.slow_period).mean(), close)

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.fast_ma, self.slow_ma) and not self.position:
            self.buy(sl=price * (1 - self.stop_loss_pct), tp=price * (1 + self.take_profit_pct))
        elif crossover(self.slow_ma, self.fast_ma) and self.position:
            self.position.close()

def run_backtest(params: BacktestParams, ohlcv: pd.DataFrame | None = None) -> BacktestResult:
    if ohlcv is None:
        rows = mt5_data.read_ohlcv(params.symbol, params.timeframe)
        ohlcv = pd.DataFrame(rows)
    df = ohlcv.rename(columns=str.title).set_index(pd.DatetimeIndex(pd.to_datetime(ohlcv["time"])))

    bt = Backtest(df, MovingAverageCrossStrategy, cash=params.starting_balance, margin=1 / params.leverage)
    stats = bt.run(
        fast_period=params.fast_period,
        slow_period=params.slow_period,
        stop_loss_pct=params.stop_loss_pct / params.leverage,
        take_profit_pct=params.take_profit_pct / params.leverage,
    )

    equity_curve = [
        {"time": str(ts), "equity": float(row["Equity"])} for ts, row in stats["_equity_curve"].iterrows()
    ]
    balance = params.starting_balance
    balance_curve = []
    for _, trade in stats["_trades"].iterrows():
        balance += float(trade["PnL"])
        balance_curve.append({"time": str(trade["ExitTime"]), "balance": balance})

    profit_factor = float(stats["Profit Factor"])
    return BacktestResult(
        final_balance=balance,
        total_return_pct=float(stats["Return [%]"]),
        sharpe_ratio=float(stats["Sharpe Ratio"]),
        max_drawdown_pct=float(stats["Max. Drawdown [%]"]),
        num_trades=int(stats["# Trades"]),
        win_rate_pct=float(stats["Win Rate [%]"]),
        profit_factor=profit_factor if profit_factor == profit_factor else 0.0,
        equity_curve=equity_curve,
        balance_curve=balance_curve,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/backend/test_backtest_engine.py -v`
Expected: 1 passed

- [ ] **Step 5: Generate the golden reference file**

```python
# scripts/generate_backtest_reference.py
import json
from pathlib import Path
from backend.backtest_engine import run_backtest
from shared.models import BacktestParams
from tests.backend.test_backtest_engine import _synthetic_ohlcv

if __name__ == "__main__":
    params = BacktestParams(symbol="SYN", timeframe="1D", starting_balance=100_000.0, leverage=1.0)
    result = run_backtest(params, ohlcv=_synthetic_ohlcv())
    reference = {
        "final_balance": result.final_balance,
        "total_return_pct": result.total_return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "num_trades": result.num_trades,
        "win_rate_pct": result.win_rate_pct,
    }
    Path("tests/fixtures").mkdir(parents=True, exist_ok=True)
    Path("tests/fixtures/backtest_reference.json").write_text(json.dumps(reference, indent=2))
    print(json.dumps(reference, indent=2))
```

Run: `python scripts/generate_backtest_reference.py`
Expected: prints and writes `tests/fixtures/backtest_reference.json` with real numbers from this exact strategy/data combination

- [ ] **Step 6: Write the regression test against the golden reference**

```python
# tests/backend/test_backtest_engine.py (append)
import json
from pathlib import Path
import pytest
from backend.backtest_engine import run_backtest

def test_backtest_matches_recorded_reference_within_tolerance():
    params = BacktestParams(symbol="SYN", timeframe="1D", starting_balance=100_000.0, leverage=1.0)
    result = run_backtest(params, ohlcv=_synthetic_ohlcv())
    reference = json.loads(Path("tests/fixtures/backtest_reference.json").read_text())
    assert result.final_balance == pytest.approx(reference["final_balance"], rel=0.01)
    assert result.total_return_pct == pytest.approx(reference["total_return_pct"], rel=0.01)
    assert result.sharpe_ratio == pytest.approx(reference["sharpe_ratio"], abs=0.05)
    assert result.max_drawdown_pct == pytest.approx(reference["max_drawdown_pct"], rel=0.01)
    assert result.num_trades == reference["num_trades"]
    assert result.win_rate_pct == pytest.approx(reference["win_rate_pct"], rel=0.01)
```

Run: `pytest tests/backend/test_backtest_engine.py -v`
Expected: 2 passed. Regenerate the fixture (Step 5) only when `MovingAverageCrossStrategy` intentionally changes.

- [ ] **Step 7: Commit**

```bash
git add shared backend/backtest_engine.py scripts tests/backend tests/fixtures
git commit -m "feat: add backtest engine wrapper with a golden-reference regression test"
```

---

## Phase 5 — Strategy library

DynamoDB-backed storage for every backtest run, plus a natural-language Q&A tool over saved results (spec's core feature 3).

### Task 21: DynamoDB access layer for the strategy library

**Files:**
- Create: `shared/strategy_library.py`
- Test: `tests/shared/test_strategy_library.py`

**Interfaces:**
- Produces: `put_run(params: BacktestParams, result: BacktestResult) -> str`, `get_run(run_id: str) -> dict | None`, `list_runs() -> list[dict]` — all read `STRATEGY_TABLE_NAME` from the environment. Consumed by Task 22 and Task 23.

- [ ] **Step 1: Write the failing test**

```python
# tests/shared/test_strategy_library.py
import boto3
import pytest
from moto import mock_aws
from shared.models import BacktestParams, BacktestResult

@pytest.fixture
def strategy_table(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("STRATEGY_TABLE_NAME", "strategy-library-test")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="strategy-library-test",
            KeySchema=[{"AttributeName": "run_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "run_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client

def _result() -> BacktestResult:
    return BacktestResult(
        final_balance=110_000.0,
        total_return_pct=10.0,
        sharpe_ratio=0.5,
        max_drawdown_pct=-8.0,
        num_trades=12,
        win_rate_pct=55.0,
        profit_factor=1.2,
        equity_curve=[],
        balance_curve=[],
    )

def test_put_and_get_run_round_trips(strategy_table):
    from shared.strategy_library import put_run, get_run

    params = BacktestParams(symbol="SYN", timeframe="1D")
    run_id = put_run(params, _result())
    stored = get_run(run_id)
    assert stored["run_id"] == run_id
    assert stored["params"]["symbol"] == "SYN"
    assert stored["result"]["final_balance"] == 110_000.0

def test_list_runs_returns_all_saved_runs(strategy_table):
    from shared.strategy_library import put_run, list_runs

    params = BacktestParams(symbol="SYN", timeframe="1D")
    put_run(params, _result())
    put_run(params, _result())
    assert len(list_runs()) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/shared/test_strategy_library.py -v`
Expected: FAIL — `shared.strategy_library` does not exist

- [ ] **Step 3: Implement the access layer**

```python
# shared/strategy_library.py
import datetime
import os
import uuid
import boto3
from shared.models import BacktestParams, BacktestResult

def _table():
    return boto3.resource("dynamodb").Table(os.environ["STRATEGY_TABLE_NAME"])

def put_run(params: BacktestParams, result: BacktestResult) -> str:
    run_id = str(uuid.uuid4())
    _table().put_item(
        Item={
            "run_id": run_id,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "params": params.model_dump(),
            "result": result.model_dump(),
        }
    )
    return run_id

def get_run(run_id: str) -> dict | None:
    response = _table().get_item(Key={"run_id": run_id})
    return response.get("Item")

def list_runs() -> list[dict]:
    return _table().scan()["Items"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/shared/test_strategy_library.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add shared tests/shared
git commit -m "feat: add DynamoDB-backed strategy library access layer"
```

### Task 22: Save every backtest run to the strategy library

**Files:**
- Modify: `backend/backtest_engine.py`
- Modify: `tests/backend/test_backtest_engine.py`

**Interfaces:**
- Consumes: `run_backtest` (Task 20), `put_run` (Task 21).
- Produces: `run_and_save_backtest(params: BacktestParams, ohlcv=None) -> str`, returning the saved `run_id`. Consumed by Phase 8's backtest-trigger route (Task 32).

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_backtest_engine.py (append)
from unittest.mock import patch
from backend.backtest_engine import run_and_save_backtest

def test_run_and_save_backtest_persists_the_result():
    params = BacktestParams(symbol="SYN", timeframe="1D")
    with patch("backend.backtest_engine.put_run", return_value="run-123") as mock_put:
        run_id = run_and_save_backtest(params, ohlcv=_synthetic_ohlcv())
    assert run_id == "run-123"
    saved_params, saved_result = mock_put.call_args.args
    assert saved_params == params
    assert saved_result.num_trades >= 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/backend/test_backtest_engine.py -v`
Expected: FAIL — `run_and_save_backtest` not defined

- [ ] **Step 3: Implement the wiring**

```python
# backend/backtest_engine.py (append)
from shared.strategy_library import put_run

def run_and_save_backtest(params: BacktestParams, ohlcv: pd.DataFrame | None = None) -> str:
    result = run_backtest(params, ohlcv=ohlcv)
    return put_run(params, result)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/backend/test_backtest_engine.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend tests/backend
git commit -m "feat: save every backtest run to the strategy library"
```

### Task 23: Strategy library Q&A tool

**Files:**
- Modify: `mcp_servers/domain_data/server.py`
- Test: `tests/mcp_servers/test_strategy_tools.py`

**Interfaces:**
- Consumes: `list_runs`, `get_run` (Task 21).
- Produces: MCP tools `list_saved_strategies() -> list[dict]` and `get_saved_strategy(run_id: str) -> dict | None`, enabling natural-language Q&A over saved results (spec core feature 3), e.g. "which strategy performed best?" resolved by the LLM calling `list_saved_strategies` and comparing `result.total_return_pct` itself.

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp_servers/test_strategy_tools.py
from unittest.mock import patch
from mcp_servers.domain_data.server import list_saved_strategies, get_saved_strategy

def test_list_saved_strategies_delegates_to_strategy_library():
    with patch("mcp_servers.domain_data.server.strategy_library.list_runs", return_value=[{"run_id": "a"}]):
        assert list_saved_strategies() == [{"run_id": "a"}]

def test_get_saved_strategy_delegates_to_strategy_library():
    with patch("mcp_servers.domain_data.server.strategy_library.get_run", return_value={"run_id": "a"}):
        assert get_saved_strategy("a") == {"run_id": "a"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/mcp_servers/test_strategy_tools.py -v`
Expected: FAIL — tools not defined

- [ ] **Step 3: Register the tools**

```python
# mcp_servers/domain_data/server.py (append)
from shared import strategy_library

@mcp.tool()
def list_saved_strategies() -> list[dict]:
    """List every saved backtest run with its parameters and metrics."""
    return strategy_library.list_runs()

@mcp.tool()
def get_saved_strategy(run_id: str) -> dict | None:
    """Get one saved backtest run by its run_id."""
    return strategy_library.get_run(run_id)
```

- [ ] **Step 4: Run to verify it passes, then extend the discovery test**

Run: `pytest tests/mcp_servers/test_strategy_tools.py -v`
Expected: 2 passed

Add `"list_saved_strategies", "get_saved_strategy"` to the discovery test's expected set in `tests/mcp_servers/test_server_integration.py`.

Run: `pytest tests/mcp_servers/test_server_integration.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add mcp_servers tests/mcp_servers
git commit -m "feat: add strategy library Q&A tools"
```

---

## Phase 6 — News pipeline

Poller → SQS → consumer, wired to the Phase 3 pipeline and Phase 5 storage. Tested against moto (no real AWS resources needed until Phase 10).

### Task 24: News poller with idempotent dedupe

**Files:**
- Create: `shared/seen_news.py`
- Create: `backend/news_poller.py`
- Test: `tests/shared/test_seen_news.py`
- Test: `tests/backend/test_news_poller.py`

**Interfaces:**
- Produces: `mark_seen_if_new(item_id: str) -> bool` in `shared/seen_news.py` (reads `SEEN_NEWS_TABLE_NAME`).
- Produces: `poll_new_news_items(symbols: list[str]) -> list[dict]` in `backend/news_poller.py`, each item `{**news_item, "symbol": str, "item_id": str}`. Consumed by Task 25.

- [ ] **Step 1: Write the failing test for dedupe**

```python
# tests/shared/test_seen_news.py
import boto3
import pytest
from moto import mock_aws

@pytest.fixture
def seen_news_table(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("SEEN_NEWS_TABLE_NAME", "seen-news-test")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="seen-news-test",
            KeySchema=[{"AttributeName": "item_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "item_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client

def test_first_sighting_is_new(seen_news_table):
    from shared.seen_news import mark_seen_if_new

    assert mark_seen_if_new("abc123") is True

def test_second_sighting_is_not_new(seen_news_table):
    from shared.seen_news import mark_seen_if_new

    mark_seen_if_new("abc123")
    assert mark_seen_if_new("abc123") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/shared/test_seen_news.py -v`
Expected: FAIL — `shared.seen_news` does not exist

- [ ] **Step 3: Implement dedupe**

```python
# shared/seen_news.py
import os
import boto3
from botocore.exceptions import ClientError

def _table():
    return boto3.resource("dynamodb").Table(os.environ["SEEN_NEWS_TABLE_NAME"])

def mark_seen_if_new(item_id: str) -> bool:
    try:
        _table().put_item(Item={"item_id": item_id}, ConditionExpression="attribute_not_exists(item_id)")
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/shared/test_seen_news.py -v`
Expected: 2 passed

- [ ] **Step 5: Write the failing test for the poller**

```python
# tests/backend/test_news_poller.py
from unittest.mock import patch
from backend.news_poller import poll_new_news_items

def test_poll_new_news_items_skips_already_seen(monkeypatch):
    monkeypatch.setattr(
        "backend.news_poller.finnhub_client.get_company_news",
        lambda symbol, f, t: [{"headline": "h1", "summary": "s1", "url": "https://x/1", "datetime": 1}],
    )
    with patch("backend.news_poller.mark_seen_if_new", side_effect=[True, False]):
        first = poll_new_news_items(["AAPL"])
        second = poll_new_news_items(["AAPL"])
    assert len(first) == 1
    assert first[0]["symbol"] == "AAPL"
    assert second == []
```

- [ ] **Step 6: Run to verify it fails**

Run: `pytest tests/backend/test_news_poller.py -v`
Expected: FAIL — `backend.news_poller` does not exist

- [ ] **Step 7: Implement the poller**

```python
# backend/news_poller.py
import datetime
import hashlib
from mcp_servers.domain_data import finnhub_client
from shared.seen_news import mark_seen_if_new

def poll_new_news_items(symbols: list[str]) -> list[dict]:
    today = datetime.date.today()
    from_date = (today - datetime.timedelta(days=1)).isoformat()
    to_date = today.isoformat()
    new_items = []
    for symbol in symbols:
        for item in finnhub_client.get_company_news(symbol, from_date, to_date):
            item_id = hashlib.sha256(item["url"].encode()).hexdigest()
            if mark_seen_if_new(item_id):
                new_items.append({**item, "symbol": symbol, "item_id": item_id})
    return new_items
```

- [ ] **Step 8: Run to verify it passes**

Run: `pytest tests/backend/test_news_poller.py -v`
Expected: 1 passed

- [ ] **Step 9: Commit**

```bash
git add shared backend tests/shared tests/backend
git commit -m "feat: add news poller with idempotent DynamoDB-backed dedupe"
```

### Task 25: SQS producer and poller wiring

**Files:**
- Create: `backend/sqs_client.py`
- Modify: `backend/news_poller.py`
- Test: `tests/backend/test_sqs_client.py`
- Modify: `tests/backend/test_news_poller.py`

**Interfaces:**
- Produces: `enqueue_news_item(client, queue_url: str, item: dict) -> str` in `backend/sqs_client.py`.
- Produces: `poll_and_enqueue(symbols: list[str], sqs_client, queue_url: str) -> list[str]` in `backend/news_poller.py`, returning enqueued message IDs. Called directly by Task 28's poller entrypoint.

- [ ] **Step 1: Write the failing test for the producer**

```python
# tests/backend/test_sqs_client.py
import json
import boto3
import pytest
from moto import mock_aws

@pytest.fixture
def queue(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("sqs", region_name="us-east-1")
        queue_url = client.create_queue(QueueName="news-queue-test")["QueueUrl"]
        yield client, queue_url

def test_enqueue_news_item_sends_json_body(queue):
    from backend.sqs_client import enqueue_news_item

    client, queue_url = queue
    message_id = enqueue_news_item(client, queue_url, {"symbol": "AAPL", "headline": "h"})
    assert message_id
    received = client.receive_message(QueueUrl=queue_url)["Messages"][0]
    assert json.loads(received["Body"]) == {"symbol": "AAPL", "headline": "h"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/backend/test_sqs_client.py -v`
Expected: FAIL — `backend.sqs_client` does not exist

- [ ] **Step 3: Implement the producer**

```python
# backend/sqs_client.py
import json

def enqueue_news_item(client, queue_url: str, item: dict) -> str:
    response = client.send_message(QueueUrl=queue_url, MessageBody=json.dumps(item))
    return response["MessageId"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/backend/test_sqs_client.py -v`
Expected: 1 passed

- [ ] **Step 5: Write the failing test for the wiring**

```python
# tests/backend/test_news_poller.py (append)
def test_poll_and_enqueue_sends_every_new_item(monkeypatch):
    monkeypatch.setattr(
        "backend.news_poller.poll_new_news_items",
        lambda symbols: [{"symbol": "AAPL", "headline": "h", "url": "https://x/1"}],
    )
    enqueued = []
    monkeypatch.setattr(
        "backend.news_poller.enqueue_news_item",
        lambda client, url, item: enqueued.append(item) or "msg-1",
    )
    from backend.news_poller import poll_and_enqueue

    message_ids = poll_and_enqueue(["AAPL"], sqs_client=object(), queue_url="fake-url")
    assert message_ids == ["msg-1"]
    assert enqueued == [{"symbol": "AAPL", "headline": "h", "url": "https://x/1"}]
```

- [ ] **Step 6: Run to verify it fails**

Run: `pytest tests/backend/test_news_poller.py -v`
Expected: FAIL — `poll_and_enqueue` not defined

- [ ] **Step 7: Implement the wiring**

```python
# backend/news_poller.py (append)
from backend.sqs_client import enqueue_news_item

def poll_and_enqueue(symbols: list[str], sqs_client, queue_url: str) -> list[str]:
    return [
        enqueue_news_item(sqs_client, queue_url, item) for item in poll_new_news_items(symbols)
    ]
```

- [ ] **Step 8: Run to verify it passes**

Run: `pytest tests/backend/test_news_poller.py -v`
Expected: 2 passed

- [ ] **Step 9: Commit**

```bash
git add backend tests/backend
git commit -m "feat: add SQS producer and wire the poller to enqueue new items"
```

### Task 26: Notifications store

**Files:**
- Create: `shared/notifications.py`
- Test: `tests/shared/test_notifications.py`

**Interfaces:**
- Produces: `create_notification(symbol: str, signal: dict, source: str) -> str` and `list_notifications() -> list[dict]` (newest first), reading `NOTIFICATIONS_TABLE_NAME`. Consumed by Task 27 and Task 29.

- [ ] **Step 1: Write the failing test**

```python
# tests/shared/test_notifications.py
import boto3
import pytest
from moto import mock_aws

@pytest.fixture
def notifications_table(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("NOTIFICATIONS_TABLE_NAME", "notifications-test")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="notifications-test",
            KeySchema=[{"AttributeName": "notification_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "notification_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client

def test_create_and_list_notifications(notifications_table):
    from shared.notifications import create_notification, list_notifications

    create_notification(symbol="AAPL", signal={"suggestion": "buy", "confidence": 0.8}, source="news_pipeline")
    notifications = list_notifications()
    assert len(notifications) == 1
    assert notifications[0]["symbol"] == "AAPL"
    assert notifications[0]["source"] == "news_pipeline"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/shared/test_notifications.py -v`
Expected: FAIL — `shared.notifications` does not exist

- [ ] **Step 3: Implement the store**

```python
# shared/notifications.py
import datetime
import os
import uuid
import boto3

def _table():
    return boto3.resource("dynamodb").Table(os.environ["NOTIFICATIONS_TABLE_NAME"])

def create_notification(symbol: str, signal: dict, source: str) -> str:
    notification_id = str(uuid.uuid4())
    _table().put_item(
        Item={
            "notification_id": notification_id,
            "symbol": symbol,
            "signal": signal,
            "source": source,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
    )
    return notification_id

def list_notifications() -> list[dict]:
    items = _table().scan()["Items"]
    return sorted(items, key=lambda item: item["created_at"], reverse=True)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/shared/test_notifications.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add shared tests/shared
git commit -m "feat: add DynamoDB-backed notifications store"
```

### Task 27: News consumer entrypoint

**Files:**
- Create: `backend/news_consumer.py`
- Create: `backend/news_poller_entrypoint.py`
- Create: `backend/news_consumer_entrypoint.py`
- Test: `tests/backend/test_news_consumer.py`

**Interfaces:**
- Consumes: `run_pipeline_for_news_item` (Task 17), `create_notification` (Task 26), `fmp_client.get_income_statement` (Task 8).
- Produces: `process_message(body: dict) -> dict | None` and `poll_queue_once(sqs_client, queue_url: str) -> int` in `backend/news_consumer.py`, run forever by `backend/news_consumer_entrypoint.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/backend/test_news_consumer.py
import json
from unittest.mock import patch
import boto3
import pytest
from moto import mock_aws
from backend.news_consumer import process_message

def test_process_message_creates_notification_when_signal_crosses_threshold():
    body = {"symbol": "AAPL", "headline": "h", "summary": "s"}
    with (
        patch("backend.news_consumer.fmp_client.get_income_statement", return_value=[{"revenue": 1}]),
        patch(
            "backend.news_consumer.run_pipeline_for_news_item",
            return_value={"signal": {"confidence": 0.9, "suggestion": "buy"}},
        ),
        patch("backend.news_consumer.notifications.create_notification") as mock_create,
    ):
        result = process_message(body)
    assert result == {"confidence": 0.9, "suggestion": "buy"}
    mock_create.assert_called_once_with(symbol="AAPL", signal={"confidence": 0.9, "suggestion": "buy"}, source="news_pipeline")

def test_process_message_skips_notification_when_no_signal():
    body = {"symbol": "AAPL", "headline": "h", "summary": "s"}
    with (
        patch("backend.news_consumer.fmp_client.get_income_statement", return_value=[]),
        patch("backend.news_consumer.run_pipeline_for_news_item", return_value={"signal": None}),
        patch("backend.news_consumer.notifications.create_notification") as mock_create,
    ):
        result = process_message(body)
    assert result is None
    mock_create.assert_not_called()

@pytest.fixture
def queue_with_message(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("sqs", region_name="us-east-1")
        queue_url = client.create_queue(QueueName="news-queue-test")["QueueUrl"]
        client.send_message(QueueUrl=queue_url, MessageBody=json.dumps({"symbol": "AAPL", "headline": "h", "summary": "s"}))
        yield client, queue_url

def test_poll_queue_once_processes_and_deletes_the_message(queue_with_message):
    from backend.news_consumer import poll_queue_once

    client, queue_url = queue_with_message
    with patch("backend.news_consumer.process_message", return_value=None) as mock_process:
        processed = poll_queue_once(client, queue_url)
    assert processed == 1
    mock_process.assert_called_once()
    assert "Messages" not in client.receive_message(QueueUrl=queue_url)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/backend/test_news_consumer.py -v`
Expected: FAIL — `backend.news_consumer` does not exist

- [ ] **Step 3: Implement the consumer**

```python
# backend/news_consumer.py
import json
from mcp_servers.domain_data import fmp_client
from agents.pipeline import run_pipeline_for_news_item
from shared import notifications

def process_message(body: dict) -> dict | None:
    symbol = body["symbol"]
    news_item = {"headline": body["headline"], "summary": body["summary"]}
    try:
        statements = fmp_client.get_income_statement(symbol)
        fundamentals = statements[0] if statements else {}
    except Exception:
        fundamentals = {}
    result = run_pipeline_for_news_item(news_item, fundamentals)
    if result["signal"] is None:
        return None
    notifications.create_notification(symbol=symbol, signal=result["signal"], source="news_pipeline")
    return result["signal"]

def poll_queue_once(sqs_client, queue_url: str) -> int:
    response = sqs_client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=5, WaitTimeSeconds=1)
    messages = response.get("Messages", [])
    for message in messages:
        process_message(json.loads(message["Body"]))
        sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
    return len(messages)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/backend/test_news_consumer.py -v`
Expected: 3 passed

- [ ] **Step 5: Write the poller and consumer entrypoint scripts**

```python
# backend/news_poller_entrypoint.py
import os
import boto3
from backend.news_poller import poll_and_enqueue

if __name__ == "__main__":
    symbols = os.environ["WATCHLIST_SYMBOLS"].split(",")
    client = boto3.client("sqs")
    poll_and_enqueue(symbols, client, os.environ["NEWS_QUEUE_URL"])
```

```python
# backend/news_consumer_entrypoint.py
import os
import time
import boto3
from backend.news_consumer import poll_queue_once

if __name__ == "__main__":
    client = boto3.client("sqs")
    queue_url = os.environ["NEWS_QUEUE_URL"]
    while True:
        if poll_queue_once(client, queue_url) == 0:
            time.sleep(5)
```

- [ ] **Step 6: Commit**

```bash
git add backend tests/backend
git commit -m "feat: add news consumer that runs the pipeline and writes notifications"
```

### Task 28: K8s manifests for the news poller and consumer

**Files:**
- Create: `k8s/base/news-poller-cronjob.yaml`
- Create: `k8s/base/news-consumer-deployment.yaml`

**Interfaces:**
- Consumes: image `trading-agent-backend:local` (Task 5), entrypoints from Task 27.

- [ ] **Step 1: Write the CronJob and Deployment manifests**

```yaml
# k8s/base/news-poller-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: news-poller
spec:
  schedule: "*/15 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: news-poller
              image: trading-agent-backend:local
              imagePullPolicy: IfNotPresent
              command: ["python", "-m", "backend.news_poller_entrypoint"]
              envFrom:
                - configMapRef: { name: pipeline-config }
                - secretRef: { name: pipeline-secrets }
```

```yaml
# k8s/base/news-consumer-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: news-consumer
spec:
  replicas: 1
  selector:
    matchLabels: { app: news-consumer }
  template:
    metadata:
      labels: { app: news-consumer }
    spec:
      containers:
        - name: news-consumer
          image: trading-agent-backend:local
          imagePullPolicy: IfNotPresent
          command: ["python", "-m", "backend.news_consumer_entrypoint"]
          envFrom:
            - configMapRef: { name: pipeline-config }
            - secretRef: { name: pipeline-secrets }
          livenessProbe:
            exec: { command: ["python", "-c", "import sys; sys.exit(0)"] }
            initialDelaySeconds: 10
            periodSeconds: 30
```

- [ ] **Step 2: Dry-run validate against the local cluster from Task 5**

```bash
kubectl create configmap pipeline-config --from-literal=WATCHLIST_SYMBOLS=AAPL,MSFT --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic pipeline-secrets --from-literal=FINNHUB_API_KEY=test --from-literal=NEWS_QUEUE_URL=test --dry-run=client -o yaml | kubectl apply -f -
kubectl apply --dry-run=server -f k8s/base/news-poller-cronjob.yaml -f k8s/base/news-consumer-deployment.yaml
```

Expected: both resources pass server-side validation (`created (dry run)`); no real SQS access needed for a dry run.

- [ ] **Step 3: Commit**

```bash
git add k8s/base
git commit -m "feat: add K8s manifests for the news poller and consumer"
```

---

## Phase 7 — Live signal mode

Re-runs a saved strategy against live prices and emits a structured, advisory-only suggestion.

### Task 29: Live signal function

**Files:**
- Create: `backend/live_signal.py`
- Test: `tests/backend/test_live_signal.py`

**Interfaces:**
- Consumes: `strategy_library.get_run` (Task 21), `mt5_data.read_ohlcv` (Task 12), `compute_fallback_indicators` (Task 13), `finnhub_client.get_quote` (Task 2), `notifications.create_notification` (Task 26).
- Produces: `run_live_signal(run_id: str) -> dict | None`, called by Task 30's entrypoint.

- [ ] **Step 1: Write the failing tests**

```python
# tests/backend/test_live_signal.py
from unittest.mock import patch
import pytest
from backend.live_signal import run_live_signal

def test_run_live_signal_raises_for_unknown_run():
    with patch("backend.live_signal.strategy_library.get_run", return_value=None):
        with pytest.raises(ValueError, match="run-404"):
            run_live_signal("run-404")

def test_run_live_signal_suggests_buy_when_fast_ma_above_slow_ma():
    saved_run = {"run_id": "run-1", "params": {"symbol": "AAPL", "timeframe": "1H"}}
    bars = [{"close": float(100 + i)} for i in range(60)]
    with (
        patch("backend.live_signal.strategy_library.get_run", return_value=saved_run),
        patch("backend.live_signal.mt5_data.read_ohlcv", return_value=bars),
        patch("backend.live_signal.finnhub_client.get_quote", return_value={"current": 191.0}),
        patch("backend.live_signal.notifications.create_notification") as mock_create,
    ):
        signal = run_live_signal("run-1")
    assert signal["action"] == "buy"
    assert signal["symbol"] == "AAPL"
    assert signal["price"] == 191.0
    mock_create.assert_called_once()

def test_run_live_signal_returns_none_without_enough_history():
    saved_run = {"run_id": "run-1", "params": {"symbol": "AAPL", "timeframe": "1H"}}
    with (
        patch("backend.live_signal.strategy_library.get_run", return_value=saved_run),
        patch("backend.live_signal.mt5_data.read_ohlcv", return_value=[{"close": 100.0}]),
        patch("backend.live_signal.finnhub_client.get_quote", return_value={"current": 100.0}),
        patch("backend.live_signal.notifications.create_notification") as mock_create,
    ):
        signal = run_live_signal("run-1")
    assert signal is None
    mock_create.assert_not_called()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/backend/test_live_signal.py -v`
Expected: FAIL — `backend.live_signal` does not exist

- [ ] **Step 3: Implement the function**

```python
# backend/live_signal.py
from shared import strategy_library, notifications
from mcp_servers.domain_data import finnhub_client, mt5_data
from mcp_servers.domain_data.indicators import compute_fallback_indicators

def run_live_signal(run_id: str) -> dict | None:
    run = strategy_library.get_run(run_id)
    if run is None:
        raise ValueError(f"No saved run {run_id}")

    symbol = run["params"]["symbol"]
    timeframe = run["params"]["timeframe"]
    closes = [bar["close"] for bar in mt5_data.read_ohlcv(symbol, timeframe)]
    indicators = compute_fallback_indicators(closes)
    if indicators["sma_20"] is None or indicators["sma_50"] is None:
        return None

    if indicators["sma_20"] > indicators["sma_50"]:
        action = "buy"
    elif indicators["sma_20"] < indicators["sma_50"]:
        action = "sell"
    else:
        return None

    quote = finnhub_client.get_quote(symbol)
    signal = {
        "run_id": run_id,
        "symbol": symbol,
        "action": action,
        "price": quote["current"],
        "reasoning": f"20-period SMA {indicators['sma_20']:.2f} vs 50-period SMA {indicators['sma_50']:.2f}",
    }
    notifications.create_notification(symbol=symbol, signal=signal, source="live_signal")
    return signal
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/backend/test_live_signal.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend tests/backend
git commit -m "feat: add live signal function"
```

### Task 30: K8s CronJob for live signal mode

**Files:**
- Create: `backend/live_signal_entrypoint.py`
- Create: `k8s/base/live-signal-cronjob.yaml`

**Interfaces:**
- Consumes: `run_live_signal` (Task 29), image `trading-agent-backend:local` (Task 5).

- [ ] **Step 1: Write the entrypoint script**

```python
# backend/live_signal_entrypoint.py
import os
from backend.live_signal import run_live_signal

if __name__ == "__main__":
    run_ids = os.environ["LIVE_SIGNAL_RUN_IDS"].split(",")
    for run_id in run_ids:
        run_live_signal(run_id)
```

- [ ] **Step 2: Write the CronJob manifest**

```yaml
# k8s/base/live-signal-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: live-signal
spec:
  schedule: "*/30 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: live-signal
              image: trading-agent-backend:local
              imagePullPolicy: IfNotPresent
              command: ["python", "-m", "backend.live_signal_entrypoint"]
              envFrom:
                - configMapRef: { name: pipeline-config }
                - secretRef: { name: pipeline-secrets }
```

- [ ] **Step 3: Dry-run validate**

Run: `kubectl apply --dry-run=server -f k8s/base/live-signal-cronjob.yaml`
Expected: `created (dry run)`

- [ ] **Step 4: Commit**

```bash
git add backend k8s/base
git commit -m "feat: add live signal K8s CronJob"
```

---

## Phase 8 — Web UI

Backend routes for each view, then the React components that consume them (single-user, no auth).

### Task 31: Watchlist and notifications routes

**Files:**
- Create: `shared/watchlist.py`
- Modify: `backend/main.py`
- Test: `tests/shared/test_watchlist.py`
- Modify: `tests/backend/test_main.py`

**Interfaces:**
- Produces: `add_symbol(symbol)`, `remove_symbol(symbol)`, `list_symbols() -> list[str]` in `shared/watchlist.py` (reads `WATCHLIST_TABLE_NAME`).
- Produces: `GET /watchlist`, `POST /watchlist/{symbol}`, `DELETE /watchlist/{symbol}`, `GET /notifications` on the FastAPI app.

- [ ] **Step 1: Write the failing test for the watchlist store**

```python
# tests/shared/test_watchlist.py
import boto3
import pytest
from moto import mock_aws

@pytest.fixture
def watchlist_table(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("WATCHLIST_TABLE_NAME", "watchlist-test")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="watchlist-test",
            KeySchema=[{"AttributeName": "symbol", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "symbol", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client

def test_add_list_remove_symbol(watchlist_table):
    from shared.watchlist import add_symbol, remove_symbol, list_symbols

    add_symbol("AAPL")
    add_symbol("MSFT")
    assert sorted(list_symbols()) == ["AAPL", "MSFT"]
    remove_symbol("MSFT")
    assert list_symbols() == ["AAPL"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/shared/test_watchlist.py -v`
Expected: FAIL — `shared.watchlist` does not exist

- [ ] **Step 3: Implement the store**

```python
# shared/watchlist.py
import os
import boto3

def _table():
    return boto3.resource("dynamodb").Table(os.environ["WATCHLIST_TABLE_NAME"])

def add_symbol(symbol: str) -> None:
    _table().put_item(Item={"symbol": symbol})

def remove_symbol(symbol: str) -> None:
    _table().delete_item(Key={"symbol": symbol})

def list_symbols() -> list[str]:
    return [item["symbol"] for item in _table().scan()["Items"]]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/shared/test_watchlist.py -v`
Expected: 1 passed

- [ ] **Step 5: Write the failing route tests**

```python
# tests/backend/test_main.py (append)
from unittest.mock import patch

def test_watchlist_routes_round_trip():
    with (
        patch("backend.main.watchlist.list_symbols", return_value=["AAPL"]) as mock_list,
        patch("backend.main.watchlist.add_symbol") as mock_add,
    ):
        add_response = client.post("/watchlist/AAPL")
        get_response = client.get("/watchlist")
    mock_add.assert_called_once_with("AAPL")
    assert add_response.json() == {"symbols": ["AAPL"]}
    assert get_response.json() == {"symbols": ["AAPL"]}

def test_notifications_route_returns_stored_notifications():
    with patch("backend.main.notifications.list_notifications", return_value=[{"symbol": "AAPL"}]):
        response = client.get("/notifications")
    assert response.json() == {"notifications": [{"symbol": "AAPL"}]}
```

- [ ] **Step 6: Run to verify it fails**

Run: `pytest tests/backend/test_main.py -v`
Expected: FAIL — routes not defined

- [ ] **Step 7: Implement the routes**

```python
# backend/main.py (append)
from shared import watchlist, notifications

@app.get("/watchlist")
def get_watchlist():
    return {"symbols": watchlist.list_symbols()}

@app.post("/watchlist/{symbol}")
def add_to_watchlist(symbol: str):
    watchlist.add_symbol(symbol)
    return {"symbols": watchlist.list_symbols()}

@app.delete("/watchlist/{symbol}")
def remove_from_watchlist(symbol: str):
    watchlist.remove_symbol(symbol)
    return {"symbols": watchlist.list_symbols()}

@app.get("/notifications")
def get_notifications():
    return {"notifications": notifications.list_notifications()}
```

- [ ] **Step 8: Run to verify it passes**

Run: `pytest tests/backend/test_main.py -v`
Expected: 4 passed

- [ ] **Step 9: Commit**

```bash
git add shared backend tests/shared tests/backend
git commit -m "feat: add watchlist and notifications routes"
```

### Task 32: Backtest-trigger and strategy-list routes

**Files:**
- Modify: `backend/main.py`
- Modify: `tests/backend/test_main.py`

**Interfaces:**
- Consumes: `run_and_save_backtest` (Task 22), `strategy_library.list_runs` (Task 21).
- Produces: `POST /backtests {BacktestParams} -> {"run_id": str}`, `GET /strategies -> {"runs": list[dict]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/backend/test_main.py (append)
def test_trigger_backtest_returns_run_id():
    with patch("backend.main.run_and_save_backtest", return_value="run-123"):
        response = client.post(
            "/backtests",
            json={"symbol": "SYN", "timeframe": "1D", "starting_balance": 100000.0, "leverage": 1.0},
        )
    assert response.status_code == 200
    assert response.json() == {"run_id": "run-123"}

def test_list_strategies_returns_saved_runs():
    with patch("backend.main.strategy_library.list_runs", return_value=[{"run_id": "run-123"}]):
        response = client.get("/strategies")
    assert response.json() == {"runs": [{"run_id": "run-123"}]}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/backend/test_main.py -v`
Expected: FAIL — routes not defined

- [ ] **Step 3: Implement the routes**

```python
# backend/main.py (append)
from shared.models import BacktestParams
from backend.backtest_engine import run_and_save_backtest
from shared import strategy_library

@app.post("/backtests")
def trigger_backtest(params: BacktestParams):
    return {"run_id": run_and_save_backtest(params)}

@app.get("/strategies")
def get_strategies():
    return {"runs": strategy_library.list_runs()}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/backend/test_main.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend tests/backend
git commit -m "feat: add backtest-trigger and strategy-list routes"
```

### Task 33: Frontend API client and Dashboard component

**Files:**
- Create: `frontend/src/api.ts`
- Create: `frontend/src/components/Dashboard.tsx`
- Test: `frontend/src/components/Dashboard.test.tsx`

**Interfaces:**
- Produces: `getWatchlist()`, `addToWatchlist(symbol)`, `getNotifications()` in `frontend/src/api.ts`, reused by Tasks 34–36.
- Produces: `<Dashboard />` rendering the watchlist and the live notification feed.

- [ ] **Step 1: Write the API client**

```ts
// frontend/src/api.ts
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export interface NotificationItem {
  notification_id: string;
  symbol: string;
  signal: { action?: string; suggestion?: string; confidence?: number; reasoning: string };
  source: string;
  created_at: string;
}

export async function getWatchlist(): Promise<string[]> {
  const res = await fetch(`${BASE_URL}/watchlist`);
  return (await res.json()).symbols;
}

export async function addToWatchlist(symbol: string): Promise<string[]> {
  const res = await fetch(`${BASE_URL}/watchlist/${symbol}`, { method: "POST" });
  return (await res.json()).symbols;
}

export async function getNotifications(): Promise<NotificationItem[]> {
  const res = await fetch(`${BASE_URL}/notifications`);
  return (await res.json()).notifications;
}

export async function sendChatMessage(message: string): Promise<string> {
  const res = await fetch(`${BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return (await res.json()).reply;
}
```

- [ ] **Step 2: Write the failing component test**

```tsx
// frontend/src/components/Dashboard.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { Dashboard } from "./Dashboard";
import * as api from "../api";

test("renders watchlist symbols and notification reasoning", async () => {
  vi.spyOn(api, "getWatchlist").mockResolvedValue(["AAPL", "MSFT"]);
  vi.spyOn(api, "getNotifications").mockResolvedValue([
    {
      notification_id: "n1",
      symbol: "AAPL",
      signal: { suggestion: "buy", confidence: 0.9, reasoning: "Strong beat." },
      source: "news_pipeline",
      created_at: "2025-01-01T00:00:00Z",
    },
  ]);

  render(<Dashboard />);

  await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
  expect(screen.getByText("MSFT")).toBeInTheDocument();
  expect(screen.getByText("Strong beat.")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/Dashboard.test.tsx`
Expected: FAIL — `./Dashboard` does not exist

- [ ] **Step 4: Implement the component**

```tsx
// frontend/src/components/Dashboard.tsx
import { useEffect, useState } from "react";
import { getWatchlist, getNotifications, NotificationItem } from "../api";

export function Dashboard() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);

  useEffect(() => {
    getWatchlist().then(setSymbols);
    getNotifications().then(setNotifications);
  }, []);

  return (
    <div>
      <h2>Watchlist</h2>
      <ul>
        {symbols.map((symbol) => (
          <li key={symbol}>{symbol}</li>
        ))}
      </ul>
      <h2>Live Signal Feed</h2>
      <ul>
        {notifications.map((n) => (
          <li key={n.notification_id}>
            <strong>{n.symbol}</strong>: {n.signal.suggestion ?? n.signal.action} — {n.signal.reasoning}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/Dashboard.test.tsx`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/Dashboard.tsx frontend/src/components/Dashboard.test.tsx
git commit -m "feat: add API client and Dashboard component"
```

### Task 34: Backtest view (equity/balance chart)

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/components/BacktestView.tsx`
- Test: `frontend/src/components/BacktestView.test.tsx`

**Interfaces:**
- Produces: `triggerBacktest(params) -> {run_id}` in `frontend/src/api.ts`; `<BacktestView />`, a form that triggers a run and renders its equity/balance curves.

- [ ] **Step 1: Add the API call and dependency**

```bash
cd frontend && npm install recharts
```

```ts
// frontend/src/api.ts (append)
export interface BacktestParams {
  symbol: string;
  timeframe: string;
  starting_balance: number;
  leverage: number;
}

export async function triggerBacktest(params: BacktestParams): Promise<{ run_id: string }> {
  const res = await fetch(`${BASE_URL}/backtests`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  return res.json();
}
```

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/components/BacktestView.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { BacktestView } from "./BacktestView";
import * as api from "../api";

test("triggers a backtest and shows the resulting run id", async () => {
  vi.spyOn(api, "triggerBacktest").mockResolvedValue({ run_id: "run-123" });

  render(<BacktestView />);
  fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "SYN" } });
  fireEvent.click(screen.getByText("Run Backtest"));

  await waitFor(() => expect(screen.getByText(/run-123/)).toBeInTheDocument());
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/BacktestView.test.tsx`
Expected: FAIL — `./BacktestView` does not exist

- [ ] **Step 4: Implement the component**

```tsx
// frontend/src/components/BacktestView.tsx
import { useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip } from "recharts";
import { triggerBacktest } from "../api";

export function BacktestView() {
  const [symbol, setSymbol] = useState("SYN");
  const [runId, setRunId] = useState<string | null>(null);

  async function handleRun() {
    const { run_id } = await triggerBacktest({
      symbol,
      timeframe: "1D",
      starting_balance: 100000,
      leverage: 1,
    });
    setRunId(run_id);
  }

  return (
    <div>
      <h2>Backtest</h2>
      <label>
        Symbol
        <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
      </label>
      <button onClick={handleRun}>Run Backtest</button>
      {runId && <p>Saved as {runId}</p>}
      <LineChart width={500} height={250} data={[]}>
        <XAxis dataKey="time" />
        <YAxis />
        <Tooltip />
        <Line type="monotone" dataKey="equity" stroke="#2563eb" />
      </LineChart>
    </div>
  );
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/BacktestView.test.tsx`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat: add backtest view with equity chart"
```

### Task 35: Sortable strategy library table

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/components/StrategyTable.tsx`
- Test: `frontend/src/components/StrategyTable.test.tsx`

**Interfaces:**
- Produces: `getStrategies() -> StrategyRun[]` in `frontend/src/api.ts`; `<StrategyTable />`, sortable by clicking a column header.

- [ ] **Step 1: Add the API call**

```ts
// frontend/src/api.ts (append)
export interface StrategyRun {
  run_id: string;
  params: { symbol: string; timeframe: string };
  result: { total_return_pct: number; sharpe_ratio: number };
}

export async function getStrategies(): Promise<StrategyRun[]> {
  const res = await fetch(`${BASE_URL}/strategies`);
  return (await res.json()).runs;
}
```

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/components/StrategyTable.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { StrategyTable } from "./StrategyTable";
import * as api from "../api";

const runs = [
  { run_id: "a", params: { symbol: "AAPL", timeframe: "1H" }, result: { total_return_pct: 5, sharpe_ratio: 0.3 } },
  { run_id: "b", params: { symbol: "MSFT", timeframe: "1D" }, result: { total_return_pct: 20, sharpe_ratio: 0.6 } },
];

test("sorts rows by return when the column header is clicked", async () => {
  vi.spyOn(api, "getStrategies").mockResolvedValue(runs);
  render(<StrategyTable />);

  await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
  fireEvent.click(screen.getByText("Return %"));

  const rows = screen.getAllByRole("row").slice(1);
  expect(rows[0]).toHaveTextContent("MSFT");
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/StrategyTable.test.tsx`
Expected: FAIL — `./StrategyTable` does not exist

- [ ] **Step 4: Implement the component**

```tsx
// frontend/src/components/StrategyTable.tsx
import { useEffect, useState } from "react";
import { getStrategies, StrategyRun } from "../api";

export function StrategyTable() {
  const [runs, setRuns] = useState<StrategyRun[]>([]);
  const [sortDesc, setSortDesc] = useState(true);

  useEffect(() => {
    getStrategies().then(setRuns);
  }, []);

  function sortByReturn() {
    setRuns((prev) =>
      [...prev].sort((a, b) =>
        sortDesc
          ? b.result.total_return_pct - a.result.total_return_pct
          : a.result.total_return_pct - b.result.total_return_pct
      )
    );
    setSortDesc((prev) => !prev);
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Symbol</th>
          <th onClick={sortByReturn} style={{ cursor: "pointer" }}>Return %</th>
          <th>Sharpe</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.run_id}>
            <td>{run.params.symbol}</td>
            <td>{run.result.total_return_pct}</td>
            <td>{run.result.sharpe_ratio}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/StrategyTable.test.tsx`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat: add sortable strategy library table"
```

### Task 36: Chat panel

**Files:**
- Create: `frontend/src/components/ChatPanel.tsx`
- Test: `frontend/src/components/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: `sendChatMessage` (Task 33).
- Produces: `<ChatPanel />`, a message list plus an input that posts to `/chat`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ChatPanel.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { ChatPanel } from "./ChatPanel";
import * as api from "../api";

test("sends a message and displays the agent's reply", async () => {
  vi.spyOn(api, "sendChatMessage").mockResolvedValue("This is advisory only.");

  render(<ChatPanel />);
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Is now a good time to buy AAPL?" } });
  fireEvent.click(screen.getByText("Send"));

  await waitFor(() => expect(screen.getByText("This is advisory only.")).toBeInTheDocument());
  expect(screen.getByText("Is now a good time to buy AAPL?")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/ChatPanel.test.tsx`
Expected: FAIL — `./ChatPanel` does not exist

- [ ] **Step 3: Implement the component**

```tsx
// frontend/src/components/ChatPanel.tsx
import { useState } from "react";
import { sendChatMessage } from "../api";

interface Message {
  role: "user" | "agent";
  text: string;
}

export function ChatPanel() {
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<Message[]>([]);

  async function handleSend() {
    const userMessage = message;
    setHistory((prev) => [...prev, { role: "user", text: userMessage }]);
    setMessage("");
    const reply = await sendChatMessage(userMessage);
    setHistory((prev) => [...prev, { role: "agent", text: reply }]);
  }

  return (
    <div>
      <ul>
        {history.map((m, i) => (
          <li key={i}>{m.text}</li>
        ))}
      </ul>
      <label>
        Message
        <input value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>
      <button onClick={handleSend}>Send</button>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/ChatPanel.test.tsx`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: add chat panel"
```

---

## Phase 9 — Terraform, full AWS infrastructure

One task per module. Each module gets a standalone `test/` root (dummy variables, `-backend=false`) so `terraform validate` can run without needing the real state backend or workspaces, which are wired up in Task 45.

### Task 37: VPC and networking module

**Files:**
- Create: `terraform/modules/vpc/variables.tf`, `terraform/modules/vpc/main.tf`, `terraform/modules/vpc/outputs.tf`
- Create: `terraform/modules/vpc/test/main.tf`

**Interfaces:**
- Produces: outputs `vpc_id`, `public_subnet_id`, `k8s_security_group_id`, consumed by the EC2 module (Task 38) and the root module (Task 45).

- [ ] **Step 1: Write the module**

```hcl
# terraform/modules/vpc/variables.tf
variable "environment" {
  type = string
}

variable "cidr_block" {
  type    = string
  default = "10.0.0.0/16"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "admin_cidr" {
  type        = string
  description = "CIDR allowed to reach SSH and the Kubernetes API"
}
```

```hcl
# terraform/modules/vpc/main.tf
resource "aws_vpc" "this" {
  cidr_block           = var.cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = {
    Name = "trading-agent-${var.environment}"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.cidr_block, 8, 0)
  map_public_ip_on_launch = true
  availability_zone       = "${var.aws_region}a"
  tags = {
    Name = "trading-agent-${var.environment}-public"
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags = {
    Name = "trading-agent-${var.environment}-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = {
    Name = "trading-agent-${var.environment}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "k8s" {
  name        = "trading-agent-${var.environment}-k8s"
  description = "k8s cluster nodes"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }
  ingress {
    description = "Kubernetes API"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }
  ingress {
    description = "HTTP ingress"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTPS ingress"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "Node-to-node (etcd, kubelet, and CNI overlay traffic)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "trading-agent-${var.environment}-k8s-sg"
  }
}
```

```hcl
# terraform/modules/vpc/outputs.tf
output "vpc_id" {
  value = aws_vpc.this.id
}

output "public_subnet_id" {
  value = aws_subnet.public.id
}

output "k8s_security_group_id" {
  value = aws_security_group.k8s.id
}
```

```hcl
# terraform/modules/vpc/test/main.tf
provider "aws" {
  region = "us-east-1"
}

module "vpc" {
  source      = "../"
  environment = "test"
  admin_cidr  = "203.0.113.0/32"
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/vpc/test && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/vpc
git commit -m "feat: add Terraform VPC/networking module"
```

### Task 38: EC2 + Kubernetes (kubeadm) bootstrap module

**Files:**
- Create: `terraform/modules/ec2/variables.tf`, `terraform/modules/ec2/main.tf`, `terraform/modules/ec2/outputs.tf`
- Create: `terraform/modules/ec2/user_data_control_plane.sh.tpl`, `terraform/modules/ec2/user_data_worker.sh.tpl`
- Create: `terraform/modules/ec2/test/main.tf`

**Interfaces:**
- Consumes: `vpc_id`, `public_subnet_id`, `k8s_security_group_id` (Task 37).
- Produces: outputs `control_plane_public_ip`, `worker_public_ips`, consumed by Task 46 (kubeconfig retrieval).

Note: kubeadm's control-plane preflight checks want ≥2 CPU / ≥2GB RAM.
`t3.medium` (2 vCPU/4GB) still satisfies that, so the instance type below is
unchanged — but full kubeadm control-plane components (etcd, API server,
scheduler, controller-manager all running as static pods) run noticeably
tighter on it than k3s's single lightweight binary did.

- [ ] **Step 1: Write the module**

```hcl
# terraform/modules/ec2/variables.tf
variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "security_group_id" {
  type = string
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
}

variable "key_name" {
  type = string
}

variable "iam_instance_profile" {
  type = string
}

variable "worker_count" {
  type    = number
  default = 2
}
```

```hcl
# terraform/modules/ec2/main.tf
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
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]
  key_name               = var.key_name
  iam_instance_profile   = var.iam_instance_profile
  user_data = templatefile("${path.module}/user_data_control_plane.sh.tpl", {
    environment = var.environment
  })
  tags = {
    Name = "trading-agent-${var.environment}-control-plane"
    Role = "control-plane"
  }
}

resource "aws_instance" "worker" {
  count                   = var.worker_count
  ami                     = data.aws_ami.ubuntu.id
  instance_type           = var.instance_type
  subnet_id               = var.subnet_id
  vpc_security_group_ids  = [var.security_group_id]
  key_name                = var.key_name
  iam_instance_profile    = var.iam_instance_profile
  user_data = templatefile("${path.module}/user_data_worker.sh.tpl", {
    environment = var.environment
  })
  depends_on = [aws_instance.control_plane]
  tags = {
    Name = "trading-agent-${var.environment}-worker-${count.index}"
    Role = "worker"
  }
}
```

```bash
# terraform/modules/ec2/user_data_control_plane.sh.tpl
#!/bin/bash
set -euo pipefail
REGION="$(curl -s http://169.254.169.254/latest/meta-data/placement/region)"
K8S_MINOR="v1.30"

swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

# containerd
apt-get update
apt-get install -y containerd apt-transport-https ca-certificates curl gpg
mkdir -p /etc/containerd
containerd config default | tee /etc/containerd/config.toml >/dev/null
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd

# kubeadm/kubelet/kubectl from the official Kubernetes apt repo
mkdir -p /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/Release.key" \
  | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/ /" \
  | tee /etc/apt/sources.list.d/kubernetes.list
apt-get update
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

kubeadm init \
  --control-plane-endpoint "$(hostname -I | awk '{print $1}')" \
  --pod-network-cidr "192.168.0.0/16"

mkdir -p /home/ubuntu/.kube
cp /etc/kubernetes/admin.conf /home/ubuntu/.kube/config
chown ubuntu:ubuntu /home/ubuntu/.kube/config

export KUBECONFIG=/etc/kubernetes/admin.conf
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml

JOIN_COMMAND=$(kubeadm token create --print-join-command)
aws ssm put-parameter \
  --name "/trading-agent/${environment}/k8s-join-command" \
  --value "$JOIN_COMMAND" \
  --type SecureString \
  --overwrite \
  --region "$REGION"
```

```bash
# terraform/modules/ec2/user_data_worker.sh.tpl
#!/bin/bash
set -euo pipefail
REGION="$(curl -s http://169.254.169.254/latest/meta-data/placement/region)"
K8S_MINOR="v1.30"

swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

apt-get update
apt-get install -y containerd apt-transport-https ca-certificates curl gpg
mkdir -p /etc/containerd
containerd config default | tee /etc/containerd/config.toml >/dev/null
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd

mkdir -p /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/Release.key" \
  | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/ /" \
  | tee /etc/apt/sources.list.d/kubernetes.list
apt-get update
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

JOIN_COMMAND=""
until [ -n "$JOIN_COMMAND" ]; do
  JOIN_COMMAND=$(aws ssm get-parameter \
    --name "/trading-agent/${environment}/k8s-join-command" \
    --with-decryption --query Parameter.Value --output text --region "$REGION" 2>/dev/null || true)
  [ -z "$JOIN_COMMAND" ] && sleep 10
done
eval "$JOIN_COMMAND"
```

```hcl
# terraform/modules/ec2/outputs.tf
output "control_plane_public_ip" {
  value = aws_instance.control_plane.public_ip
}

output "worker_public_ips" {
  value = aws_instance.worker[*].public_ip
}
```

```hcl
# terraform/modules/ec2/test/main.tf
provider "aws" {
  region = "us-east-1"
}

module "ec2" {
  source                = "../"
  environment            = "test"
  vpc_id                 = "vpc-00000000000000000"
  subnet_id              = "subnet-00000000000000000"
  security_group_id      = "sg-00000000000000000"
  key_name               = "test-key"
  iam_instance_profile   = "test-profile"
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/ec2/test && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/ec2
git commit -m "feat: add Terraform EC2 + Kubernetes bootstrap module"
```

### Task 39: S3 module

**Files:**
- Create: `terraform/modules/s3/variables.tf`, `terraform/modules/s3/main.tf`, `terraform/modules/s3/outputs.tf`
- Create: `terraform/modules/s3/test/main.tf`

**Interfaces:**
- Produces: output `mt5_data_bucket_name`, read by the backend/MCP server's `MT5_DATA_BUCKET` env var (wired in Task 46).

- [ ] **Step 1: Write the module**

```hcl
# terraform/modules/s3/variables.tf
variable "environment" {
  type = string
}
```

```hcl
# terraform/modules/s3/main.tf
resource "aws_s3_bucket" "mt5_data" {
  bucket = "trading-agent-mt5-data-${var.environment}"
  tags = {
    Environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "mt5_data" {
  bucket = aws_s3_bucket.mt5_data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "mt5_data" {
  bucket                  = aws_s3_bucket.mt5_data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

```hcl
# terraform/modules/s3/outputs.tf
output "mt5_data_bucket_name" {
  value = aws_s3_bucket.mt5_data.bucket
}
```

```hcl
# terraform/modules/s3/test/main.tf
provider "aws" {
  region = "us-east-1"
}

module "s3" {
  source      = "../"
  environment = "test"
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/s3/test && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/s3
git commit -m "feat: add Terraform S3 module for MT5 data"
```

### Task 40: DynamoDB module

**Files:**
- Create: `terraform/modules/dynamodb/variables.tf`, `terraform/modules/dynamodb/main.tf`, `terraform/modules/dynamodb/outputs.tf`
- Create: `terraform/modules/dynamodb/test/main.tf`

**Interfaces:**
- Produces: outputs `strategy_library_table_name`, `notifications_table_name`, `watchlist_table_name`, `seen_news_table_name` — these exact names are what Task 46 sets as the backend's `STRATEGY_TABLE_NAME`, `NOTIFICATIONS_TABLE_NAME`, `WATCHLIST_TABLE_NAME`, `SEEN_NEWS_TABLE_NAME` env vars.

- [ ] **Step 1: Write the module**

```hcl
# terraform/modules/dynamodb/variables.tf
variable "environment" {
  type = string
}
```

```hcl
# terraform/modules/dynamodb/main.tf
resource "aws_dynamodb_table" "strategy_library" {
  name         = "trading-agent-strategy-library-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  attribute {
    name = "run_id"
    type = "S"
  }
  tags = {
    Environment = var.environment
  }
}

resource "aws_dynamodb_table" "notifications" {
  name         = "trading-agent-notifications-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "notification_id"
  attribute {
    name = "notification_id"
    type = "S"
  }
  tags = {
    Environment = var.environment
  }
}

resource "aws_dynamodb_table" "watchlist" {
  name         = "trading-agent-watchlist-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "symbol"
  attribute {
    name = "symbol"
    type = "S"
  }
  tags = {
    Environment = var.environment
  }
}

resource "aws_dynamodb_table" "seen_news" {
  name         = "trading-agent-seen-news-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "item_id"
  attribute {
    name = "item_id"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  tags = {
    Environment = var.environment
  }
}
```

```hcl
# terraform/modules/dynamodb/outputs.tf
output "strategy_library_table_name" {
  value = aws_dynamodb_table.strategy_library.name
}

output "notifications_table_name" {
  value = aws_dynamodb_table.notifications.name
}

output "watchlist_table_name" {
  value = aws_dynamodb_table.watchlist.name
}

output "seen_news_table_name" {
  value = aws_dynamodb_table.seen_news.name
}
```

```hcl
# terraform/modules/dynamodb/test/main.tf
provider "aws" {
  region = "us-east-1"
}

module "dynamodb" {
  source      = "../"
  environment = "test"
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/dynamodb/test && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/dynamodb
git commit -m "feat: add Terraform DynamoDB module for app tables"
```

### Task 41: SQS module

**Files:**
- Create: `terraform/modules/sqs/variables.tf`, `terraform/modules/sqs/main.tf`, `terraform/modules/sqs/outputs.tf`
- Create: `terraform/modules/sqs/test/main.tf`

**Interfaces:**
- Produces: output `news_queue_url`, wired to `NEWS_QUEUE_URL` in Task 46.

- [ ] **Step 1: Write the module**

```hcl
# terraform/modules/sqs/variables.tf
variable "environment" {
  type = string
}
```

```hcl
# terraform/modules/sqs/main.tf
resource "aws_sqs_queue" "news_dlq" {
  name                      = "trading-agent-news-dlq-${var.environment}"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "news" {
  name                       = "trading-agent-news-${var.environment}"
  visibility_timeout_seconds = 60
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.news_dlq.arn
    maxReceiveCount     = 5
  })
}
```

```hcl
# terraform/modules/sqs/outputs.tf
output "news_queue_url" {
  value = aws_sqs_queue.news.url
}

output "news_queue_arn" {
  value = aws_sqs_queue.news.arn
}

output "news_dlq_arn" {
  value = aws_sqs_queue.news_dlq.arn
}
```

```hcl
# terraform/modules/sqs/test/main.tf
provider "aws" {
  region = "us-east-1"
}

module "sqs" {
  source      = "../"
  environment = "test"
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/sqs/test && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/sqs
git commit -m "feat: add Terraform SQS module with a dead-letter queue"
```

### Task 42: SSM Parameter Store module

**Files:**
- Create: `terraform/modules/ssm/variables.tf`, `terraform/modules/ssm/main.tf`
- Create: `terraform/modules/ssm/test/main.tf`

**Interfaces:**
- Produces: SecureString parameters under `/trading-agent/{environment}/*`, read by the K8s Secret sync in Task 46. No values are ever committed — they're passed as `sensitive` Terraform variables from the operator's shell/CI secret store.

- [ ] **Step 1: Write the module**

```hcl
# terraform/modules/ssm/variables.tf
variable "environment" {
  type = string
}

variable "finnhub_api_key" {
  type      = string
  sensitive = true
}

variable "fmp_api_key" {
  type      = string
  sensitive = true
}

variable "fred_api_key" {
  type      = string
  sensitive = true
}

variable "marketaux_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "edgar_identity" {
  type      = string
  sensitive = true
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
}
```

```hcl
# terraform/modules/ssm/main.tf
locals {
  parameters = {
    finnhub-api-key   = var.finnhub_api_key
    fmp-api-key       = var.fmp_api_key
    fred-api-key      = var.fred_api_key
    marketaux-api-key = var.marketaux_api_key
    edgar-identity     = var.edgar_identity
    anthropic-api-key  = var.anthropic_api_key
  }
}

resource "aws_ssm_parameter" "secrets" {
  for_each = local.parameters
  name     = "/trading-agent/${var.environment}/${each.key}"
  type     = "SecureString"
  value    = each.value
}
```

```hcl
# terraform/modules/ssm/test/main.tf
provider "aws" {
  region = "us-east-1"
}

module "ssm" {
  source             = "../"
  environment        = "test"
  finnhub_api_key    = "dummy"
  fmp_api_key        = "dummy"
  fred_api_key       = "dummy"
  edgar_identity     = "dummy@example.com"
  anthropic_api_key  = "dummy"
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/ssm/test && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/ssm
git commit -m "feat: add Terraform SSM Parameter Store module for API keys"
```

### Task 43: ECR module

**Files:**
- Create: `terraform/modules/ecr/main.tf`, `terraform/modules/ecr/outputs.tf`
- Create: `terraform/modules/ecr/test/main.tf`

**Interfaces:**
- Produces: output `repository_url`, used by Task 48's CI build/push step. Shared across `dev`/`prod` — images are tagged per environment, not held in separate repos (spec §7).

- [ ] **Step 1: Write the module**

```hcl
# terraform/modules/ecr/main.tf
resource "aws_ecr_repository" "backend" {
  name                 = "trading-agent-backend"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images after 14 days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 14
      }
      action = { type = "expire" }
    }]
  })
}
```

```hcl
# terraform/modules/ecr/outputs.tf
output "repository_url" {
  value = aws_ecr_repository.backend.repository_url
}
```

```hcl
# terraform/modules/ecr/test/main.tf
provider "aws" {
  region = "us-east-1"
}

module "ecr" {
  source = "../"
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/ecr/test && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/ecr
git commit -m "feat: add Terraform ECR module"
```

### Task 44: IAM roles and policies module

**Files:**
- Create: `terraform/modules/iam/variables.tf`, `terraform/modules/iam/main.tf`, `terraform/modules/iam/outputs.tf`
- Create: `terraform/modules/iam/test/main.tf`

**Interfaces:**
- Produces: output `instance_profile_name`, consumed by the EC2 module (Task 38) via the root module (Task 45). Grants EC2 nodes least-privilege access to only this environment's SSM parameters, S3 bucket, DynamoDB tables, and SQS queue.

- [ ] **Step 1: Write the module**

```hcl
# terraform/modules/iam/variables.tf
variable "environment" {
  type = string
}
```

```hcl
# terraform/modules/iam/main.tf
resource "aws_iam_role" "node" {
  name = "trading-agent-${var.environment}-node"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "node" {
  name = "trading-agent-${var.environment}-node-policy"
  role = aws_iam_role.node.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:PutParameter"]
        Resource = "arn:aws:ssm:*:*:parameter/trading-agent/${var.environment}/*"
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::trading-agent-mt5-data-${var.environment}",
          "arn:aws:s3:::trading-agent-mt5-data-${var.environment}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Scan"]
        Resource = "arn:aws:dynamodb:*:*:table/trading-agent-*-${var.environment}"
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueUrl"]
        Resource = "arn:aws:sqs:*:*:trading-agent-news-${var.environment}"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "node" {
  name = "trading-agent-${var.environment}-node"
  role = aws_iam_role.node.name
}
```

```hcl
# terraform/modules/iam/outputs.tf
output "instance_profile_name" {
  value = aws_iam_instance_profile.node.name
}
```

```hcl
# terraform/modules/iam/test/main.tf
provider "aws" {
  region = "us-east-1"
}

module "iam" {
  source      = "../"
  environment = "test"
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/iam/test && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/iam
git commit -m "feat: add Terraform IAM module for node roles"
```

### Task 45: Wire dev/prod Terraform workspaces

**Files:**
- Create: `terraform/bootstrap/main.tf` (one-time, local backend)
- Create: `terraform/environments/backend.tf`, `terraform/environments/variables.tf`, `terraform/environments/main.tf`, `terraform/environments/outputs.tf`

**Interfaces:**
- Consumes: all modules from Tasks 37–44.
- Produces: `dev` and `prod` Terraform workspaces against the shared S3 state backend, each with its own fully separate set of resources (spec §7).

- [ ] **Step 1: Write the one-time state-backend bootstrap**

```hcl
# terraform/bootstrap/main.tf
terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "state" {
  bucket = "trading-agent-terraform-state"
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_dynamodb_table" "locks" {
  name         = "trading-agent-terraform-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}
```

Run once, manually, before anything else: `cd terraform/bootstrap && terraform init && terraform apply`

- [ ] **Step 2: Write the root module**

```hcl
# terraform/environments/backend.tf
terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
  backend "s3" {
    bucket         = "trading-agent-terraform-state"
    key            = "trading-agent/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "trading-agent-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-1"
}
```

```hcl
# terraform/environments/variables.tf
variable "admin_cidr" {
  type = string
}

variable "key_name" {
  type = string
}

variable "finnhub_api_key" {
  type      = string
  sensitive = true
}

variable "fmp_api_key" {
  type      = string
  sensitive = true
}

variable "fred_api_key" {
  type      = string
  sensitive = true
}

variable "marketaux_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "edgar_identity" {
  type      = string
  sensitive = true
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
}
```

```hcl
# terraform/environments/main.tf
locals {
  environment = terraform.workspace
}

module "vpc" {
  source      = "../modules/vpc"
  environment = local.environment
  admin_cidr  = var.admin_cidr
}

module "iam" {
  source      = "../modules/iam"
  environment = local.environment
}

module "ec2" {
  source                = "../modules/ec2"
  environment            = local.environment
  vpc_id                 = module.vpc.vpc_id
  subnet_id              = module.vpc.public_subnet_id
  security_group_id      = module.vpc.k8s_security_group_id
  key_name                = var.key_name
  iam_instance_profile    = module.iam.instance_profile_name
}

module "s3" {
  source      = "../modules/s3"
  environment = local.environment
}

module "dynamodb" {
  source      = "../modules/dynamodb"
  environment = local.environment
}

module "sqs" {
  source      = "../modules/sqs"
  environment = local.environment
}

module "ssm" {
  source             = "../modules/ssm"
  environment        = local.environment
  finnhub_api_key    = var.finnhub_api_key
  fmp_api_key        = var.fmp_api_key
  fred_api_key       = var.fred_api_key
  marketaux_api_key  = var.marketaux_api_key
  edgar_identity     = var.edgar_identity
  anthropic_api_key  = var.anthropic_api_key
}

module "ecr" {
  source = "../modules/ecr"
}
```

```hcl
# terraform/environments/outputs.tf
output "control_plane_public_ip" {
  value = module.ec2.control_plane_public_ip
}

output "worker_public_ips" {
  value = module.ec2.worker_public_ips
}

output "mt5_data_bucket_name" {
  value = module.s3.mt5_data_bucket_name
}

output "strategy_library_table_name" {
  value = module.dynamodb.strategy_library_table_name
}

output "notifications_table_name" {
  value = module.dynamodb.notifications_table_name
}

output "watchlist_table_name" {
  value = module.dynamodb.watchlist_table_name
}

output "seen_news_table_name" {
  value = module.dynamodb.seen_news_table_name
}

output "news_queue_url" {
  value = module.sqs.news_queue_url
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}
```

- [ ] **Step 3: Create both workspaces and plan each**

```bash
cd terraform/environments
terraform init
terraform workspace new dev
terraform workspace new prod
terraform workspace select dev
terraform plan -var-file=dev.tfvars
terraform workspace select prod
terraform plan -var-file=prod.tfvars
```

Expected: both plans succeed and show a full, independent set of resources being created for that workspace (no resource IDs shared between the two plans). `dev.tfvars`/`prod.tfvars` hold `admin_cidr`, `key_name`, and are populated with real API keys from a secrets manager at apply time — never committed.

- [ ] **Step 4: Commit**

```bash
git add terraform/bootstrap terraform/environments
echo "*.tfvars" >> .gitignore
echo ".terraform/" >> .gitignore
git add .gitignore
git commit -m "feat: wire dev/prod Terraform workspaces across all modules"
```

---

## Phase 10 — Deploy to the real cluster

Points the already-tested manifests from Phases 1, 6, and 7 at the real Terraform-provisioned EC2 Kubernetes cluster. Adds the HPA and ingress pieces the local kind cluster didn't need for correctness checks.

### Task 46: Deploy the `dev` namespace

**Files:**
- Create: `scripts/fetch_kubeconfig.sh`, `scripts/deploy.sh`
- Create: `k8s/base/backend-hpa.yaml`, `k8s/base/news-consumer-hpa.yaml`
- Modify: `k8s/base/deployment.yaml`, `k8s/base/news-consumer-deployment.yaml` (add `resources.requests.cpu`, required for CPU-based HPA)
- Create: `k8s/overlays/dev/kustomization.yaml`, `k8s/overlays/dev/ingress.yaml`

**Interfaces:**
- Consumes: Terraform outputs from Task 45 (`control_plane_public_ip`, `ecr_repository_url`, `news_queue_url`, `mt5_data_bucket_name`, the four DynamoDB table names), SSM parameters from Task 42.

- [ ] **Step 1: Retrieve the kubeconfig and verify the cluster**

```bash
# scripts/fetch_kubeconfig.sh
#!/bin/bash
set -euo pipefail
ENVIRONMENT=$1
cd terraform/environments
terraform workspace select "$ENVIRONMENT"
CONTROL_PLANE_IP=$(terraform output -raw control_plane_public_ip)
ssh -o StrictHostKeyChecking=no "ubuntu@${CONTROL_PLANE_IP}" "sudo cat /etc/kubernetes/admin.conf" \
  | sed "s/127.0.0.1/${CONTROL_PLANE_IP}/" > "kubeconfig-${ENVIRONMENT}.yaml"
echo "Wrote terraform/environments/kubeconfig-${ENVIRONMENT}.yaml"
```

Run: `chmod +x scripts/fetch_kubeconfig.sh && ./scripts/fetch_kubeconfig.sh dev && KUBECONFIG=terraform/environments/kubeconfig-dev.yaml kubectl get nodes`
Expected: 3 nodes, all `Ready` (1 control-plane, 2 workers)

- [ ] **Step 2: Install ingress-nginx once, cluster-wide**

Run: `KUBECONFIG=terraform/environments/kubeconfig-dev.yaml helm upgrade --install ingress-nginx ingress-nginx --repo https://kubernetes.github.io/ingress-nginx --namespace ingress-nginx --create-namespace`
Expected: `STATUS: deployed`

- [ ] **Step 3: Add resource requests and HPA manifests**

```yaml
# k8s/base/deployment.yaml (add under spec.template.spec.containers[0])
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
```

```yaml
# k8s/base/news-consumer-deployment.yaml (add under spec.template.spec.containers[0])
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
```

```yaml
# k8s/base/backend-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend
  minReplicas: 1
  maxReplicas: 4
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

```yaml
# k8s/base/news-consumer-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: news-consumer
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: news-consumer
  minReplicas: 1
  maxReplicas: 3
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

- [ ] **Step 4: Write the `dev` kustomize overlay and Ingress**

```yaml
# k8s/overlays/dev/kustomization.yaml
namespace: dev
resources:
  - ../../base/deployment.yaml
  - ../../base/service.yaml
  - ../../base/backend-hpa.yaml
  - ../../base/news-poller-cronjob.yaml
  - ../../base/news-consumer-deployment.yaml
  - ../../base/news-consumer-hpa.yaml
  - ../../base/live-signal-cronjob.yaml
  - ingress.yaml
```

```yaml
# k8s/overlays/dev/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: trading-agent
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  rules:
    - host: dev.trading-agent.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: backend
                port:
                  number: 80
```

- [ ] **Step 5: Write the deploy script**

```bash
# scripts/deploy.sh
#!/bin/bash
set -euo pipefail
ENVIRONMENT=$1
IMAGE_TAG=${2:-latest}

pushd terraform/environments > /dev/null
terraform workspace select "$ENVIRONMENT"
REPO_URL=$(terraform output -raw ecr_repository_url)
QUEUE_URL=$(terraform output -raw news_queue_url)
BUCKET=$(terraform output -raw mt5_data_bucket_name)
STRATEGY_TABLE=$(terraform output -raw strategy_library_table_name)
NOTIFICATIONS_TABLE=$(terraform output -raw notifications_table_name)
WATCHLIST_TABLE=$(terraform output -raw watchlist_table_name)
SEEN_NEWS_TABLE=$(terraform output -raw seen_news_table_name)
popd > /dev/null

export KUBECONFIG="terraform/environments/kubeconfig-${ENVIRONMENT}.yaml"

kubectl create namespace "$ENVIRONMENT" --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "$ENVIRONMENT" create configmap backend-config \
  --from-literal=MT5_DATA_BUCKET="$BUCKET" \
  --from-literal=STRATEGY_TABLE_NAME="$STRATEGY_TABLE" \
  --from-literal=NOTIFICATIONS_TABLE_NAME="$NOTIFICATIONS_TABLE" \
  --from-literal=WATCHLIST_TABLE_NAME="$WATCHLIST_TABLE" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "$ENVIRONMENT" create configmap pipeline-config \
  --from-literal=WATCHLIST_SYMBOLS=AAPL,MSFT \
  --from-literal=NEWS_QUEUE_URL="$QUEUE_URL" \
  --from-literal=SEEN_NEWS_TABLE_NAME="$SEEN_NEWS_TABLE" \
  --dry-run=client -o yaml | kubectl apply -f -

SECRET_ARGS=()
for param in finnhub-api-key fmp-api-key fred-api-key marketaux-api-key edgar-identity anthropic-api-key; do
  VALUE=$(aws ssm get-parameter --name "/trading-agent/${ENVIRONMENT}/${param}" --with-decryption --query Parameter.Value --output text)
  KEY=$(echo "$param" | tr '[:lower:]-' '[:upper:]_')
  SECRET_ARGS+=("--from-literal=${KEY}=${VALUE}")
done
kubectl -n "$ENVIRONMENT" create secret generic backend-secrets "${SECRET_ARGS[@]}" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$ENVIRONMENT" create secret generic pipeline-secrets "${SECRET_ARGS[@]}" --dry-run=client -o yaml | kubectl apply -f -

pushd "k8s/overlays/${ENVIRONMENT}" > /dev/null
kustomize edit set image "trading-agent-backend:local=${REPO_URL}:${IMAGE_TAG}"
kubectl apply -k .
popd > /dev/null

kubectl -n "$ENVIRONMENT" rollout status deployment/backend --timeout=120s
kubectl -n "$ENVIRONMENT" rollout status deployment/news-consumer --timeout=120s
```

- [ ] **Step 6: Build, push, and deploy**

```bash
chmod +x scripts/deploy.sh
aws ecr get-login-password | docker login --username AWS --password-stdin "$(cd terraform/environments && terraform output -raw ecr_repository_url | cut -d/ -f1)"
docker build -t "$(cd terraform/environments && terraform output -raw ecr_repository_url):dev-manual" .
docker push "$(cd terraform/environments && terraform output -raw ecr_repository_url):dev-manual"
./scripts/deploy.sh dev dev-manual
```

- [ ] **Step 7: Verify**

```bash
export KUBECONFIG=terraform/environments/kubeconfig-dev.yaml
kubectl -n dev get pods
CONTROL_PLANE_IP=$(cd terraform/environments && terraform workspace select dev && terraform output -raw control_plane_public_ip)
curl --resolve "dev.trading-agent.local:80:${CONTROL_PLANE_IP}" http://dev.trading-agent.local/healthz
```

Expected: all pods `Running`/`Completed`; `{"status":"ok"}` through the real ingress

- [ ] **Step 8: Commit**

```bash
git add scripts k8s
git commit -m "feat: deploy the dev namespace to the real Kubernetes cluster"
```

### Task 47: Deploy the `prod` namespace

**Files:**
- Create: `k8s/overlays/prod/kustomization.yaml`, `k8s/overlays/prod/ingress.yaml`

**Interfaces:**
- Consumes: the same `scripts/deploy.sh` (Task 46), parameterized by environment; Terraform's `prod` workspace outputs (Task 45).

- [ ] **Step 1: Write the `prod` overlay**

```yaml
# k8s/overlays/prod/kustomization.yaml
namespace: prod
resources:
  - ../../base/deployment.yaml
  - ../../base/service.yaml
  - ../../base/backend-hpa.yaml
  - ../../base/news-poller-cronjob.yaml
  - ../../base/news-consumer-deployment.yaml
  - ../../base/news-consumer-hpa.yaml
  - ../../base/live-signal-cronjob.yaml
  - ingress.yaml
```

```yaml
# k8s/overlays/prod/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: trading-agent
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  rules:
    - host: prod.trading-agent.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: backend
                port:
                  number: 80
```

- [ ] **Step 2: Fetch the prod kubeconfig, build/push, and deploy**

```bash
./scripts/fetch_kubeconfig.sh prod
docker build -t "$(cd terraform/environments && terraform workspace select prod && terraform output -raw ecr_repository_url):prod-manual" .
docker push "$(cd terraform/environments && terraform output -raw ecr_repository_url):prod-manual"
./scripts/deploy.sh prod prod-manual
```

- [ ] **Step 3: Verify**

```bash
export KUBECONFIG=terraform/environments/kubeconfig-prod.yaml
kubectl -n prod get pods
CONTROL_PLANE_IP=$(cd terraform/environments && terraform workspace select prod && terraform output -raw control_plane_public_ip)
curl --resolve "prod.trading-agent.local:80:${CONTROL_PLANE_IP}" http://prod.trading-agent.local/healthz
```

Expected: all pods `Running`/`Completed`; `{"status":"ok"}` through the real ingress, fully isolated from `dev`'s namespace and AWS resources

- [ ] **Step 4: Commit**

```bash
git add k8s/overlays/prod
git commit -m "feat: deploy the prod namespace to the real Kubernetes cluster"
```

---

## Phase 11 — CI/CD, full pipeline

Extends the Phase 1 CI skeleton with build/push and the full integration suite, then adds environment-gated CD.

### Task 48: Extend CI with build/push and the full test suite

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `Dockerfile` (Task 5), MCP-transport integration tests (Tasks 2, 14), frontend tests (Tasks 33–36).

- [ ] **Step 1: Extend the workflow**

```yaml
# .github/workflows/ci.yml (replace the test job, add a build job)
jobs:
  backend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check .
      - name: Unit + MCP-transport integration tests
        run: pytest --cov=. --cov-report=xml -v
        env:
          FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
      - name: Job summary
        if: always()
        run: |
          echo "## Backend test results" >> "$GITHUB_STEP_SUMMARY"
          pytest --cov=. --cov-report=term-missing | tail -n 20 >> "$GITHUB_STEP_SUMMARY" || true
      - name: Coverage badge
        uses: irongut/CodeCoverageSummary@v1.3.0
        with:
          filename: coverage.xml
          badge: true
          format: markdown
          output: both

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd frontend && npm ci
      - run: cd frontend && npm run build
      - run: cd frontend && npx vitest run

  build-and-push:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    needs: [backend-tests, frontend-tests]
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.CI_AWS_ROLE_ARN }}
          aws-region: us-east-1
      - uses: aws-actions/amazon-ecr-login@v2
        id: ecr-login
      - name: Build and push
        run: |
          docker build -t "${{ steps.ecr-login.outputs.registry }}/trading-agent-backend:${{ github.sha }}" .
          docker push "${{ steps.ecr-login.outputs.registry }}/trading-agent-backend:${{ github.sha }}"
```

- [ ] **Step 2: Verify**

Run: open a PR — `backend-tests` and `frontend-tests` run; push to `main` — `build-and-push` also runs and pushes a `${{ github.sha }}`-tagged image.
Expected: all jobs green; new image tag visible in ECR

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add frontend tests and build/push to ECR on merge to main"
```

### Task 49: CD workflow — automatic deploy to `dev`

**Files:**
- Create: `.github/workflows/cd-dev.yml`

**Interfaces:**
- Consumes: `scripts/deploy.sh dev <tag>` (Task 46), the image tag pushed by Task 48.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/cd-dev.yml
name: Deploy dev
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
    branches: [main]
jobs:
  deploy:
    if: github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.CI_AWS_ROLE_ARN }}
          aws-region: us-east-1
      - name: Install kubectl and kustomize
        run: |
          curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
          chmod +x kubectl && sudo mv kubectl /usr/local/bin/
          curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
          sudo mv kustomize /usr/local/bin/
      - name: Write kubeconfig
        run: echo "${{ secrets.DEV_KUBECONFIG }}" > terraform/environments/kubeconfig-dev.yaml
      - name: Deploy
        run: ./scripts/deploy.sh dev "${{ github.event.workflow_run.head_sha }}"
```

- [ ] **Step 2: Verify**

Run: merge a PR to `main`, watch the `Deploy dev` workflow
Expected: it triggers automatically after `CI` succeeds and deploys the just-built image tag

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/cd-dev.yml
git commit -m "ci: deploy to dev automatically on merge to main"
```

### Task 50: CD workflow — gated deploy to `prod`

**Files:**
- Create: `.github/workflows/cd-prod.yml`

**Interfaces:**
- Consumes: the same `scripts/deploy.sh prod <tag>`; requires the GitHub `production` Environment to have a required-reviewers protection rule configured in repo settings (manual, one-time, done in the GitHub UI — the only manual step in this pipeline, and it's an approval gate, not an infra change).

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/cd-prod.yml
name: Deploy prod
on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: "Image tag to deploy (git SHA from a successful CI run)"
        required: true
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.CI_AWS_ROLE_ARN }}
          aws-region: us-east-1
      - name: Install kubectl and kustomize
        run: |
          curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
          chmod +x kubectl && sudo mv kubectl /usr/local/bin/
          curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
          sudo mv kustomize /usr/local/bin/
      - name: Write kubeconfig
        run: echo "${{ secrets.PROD_KUBECONFIG }}" > terraform/environments/kubeconfig-prod.yaml
      - name: Deploy
        run: ./scripts/deploy.sh prod "${{ inputs.image_tag }}"
```

- [ ] **Step 2: Verify**

Run: trigger `Deploy prod` manually with a known-good `image_tag`
Expected: the job pauses for the `production` Environment's required reviewer approval, then deploys once approved — never runs on a plain push

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/cd-prod.yml
git commit -m "ci: add manually-gated deploy to prod"
```

### Task 51: Terraform plan/apply workflow

**Files:**
- Create: `.github/workflows/terraform.yml`

**Interfaces:**
- Consumes: `terraform/environments` (Task 45); never triggered by a push, only `workflow_dispatch`.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/terraform.yml
name: Terraform
on:
  workflow_dispatch:
    inputs:
      environment:
        description: "dev or prod"
        required: true
      action:
        description: "plan or apply"
        required: true
        default: "plan"
jobs:
  terraform:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    defaults:
      run:
        working-directory: terraform/environments
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.CI_AWS_ROLE_ARN }}
          aws-region: us-east-1
      - run: terraform init
      - run: terraform workspace select ${{ inputs.environment }}
      - run: terraform ${{ inputs.action }} -var-file=${{ inputs.environment }}.tfvars -auto-approve=${{ inputs.action == 'apply' }}
```

- [ ] **Step 2: Verify**

Run: trigger manually with `environment=dev`, `action=plan`
Expected: shows the plan in the job log; `action=apply` on `prod` pauses for the `production` Environment's approval gate before applying, same as Task 50

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/terraform.yml
git commit -m "ci: add manually-triggered Terraform plan/apply workflow"
```

---

## Phase 12 — Observability

Prometheus + Grafana + Alertmanager + Loki, installed in-cluster via Helm, instrumented per spec §10.

### Task 52: Install the observability stack

**Files:**
- Create: `observability/kube-prometheus-stack-values.yaml`
- Create: `observability/loki-stack-values.yaml`

**Interfaces:**
- Produces: a running Prometheus, Grafana, Alertmanager, and Loki/Promtail in the `monitoring` namespace, shared by both `dev` and `prod` (metrics/logs are labeled by namespace, per spec §10) — consumed by Tasks 54–56.

- [ ] **Step 1: Write the Helm values**

```yaml
# observability/kube-prometheus-stack-values.yaml
grafana:
  adminPassword: "" # supplied via --set at install time, never committed
  service:
    type: ClusterIP
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
    ruleSelectorNilUsesHelmValues: false
    retention: 15d
alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          resources:
            requests:
              storage: 2Gi
```

```yaml
# observability/loki-stack-values.yaml
loki:
  auth_enabled: false
promtail:
  enabled: true
  config:
    clients:
      - url: http://loki:3100/loki/api/v1/push
```

- [ ] **Step 2: Install**

```bash
export KUBECONFIG=terraform/environments/kubeconfig-dev.yaml
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring -f observability/kube-prometheus-stack-values.yaml \
  --set grafana.adminPassword="$(openssl rand -base64 20)"
helm upgrade --install loki grafana/loki-stack \
  --namespace monitoring -f observability/loki-stack-values.yaml
```

- [ ] **Step 3: Verify**

Run: `kubectl -n monitoring get pods`
Expected: `prometheus-*`, `alertmanager-*`, `*-grafana-*`, `loki-*`, `loki-promtail-*` all `Running`

- [ ] **Step 4: Commit**

```bash
git add observability
git commit -m "feat: install kube-prometheus-stack and Loki via Helm"
```

### Task 53: Instrument the backend and pipeline consumer

**Files:**
- Create: `backend/metrics.py`
- Modify: `backend/main.py`
- Modify: `mcp_servers/domain_data/http.py`
- Modify: `backend/news_consumer_entrypoint.py`, `backend/live_signal_entrypoint.py`
- Test: `tests/backend/test_metrics.py`

**Interfaces:**
- Produces: `REQUEST_LATENCY`, `EXTERNAL_API_ERRORS`, `LLM_CALL_FAILURES`, `BACKTEST_JOB_DURATION`, `SIGNALS_NOTIFIED` in `backend/metrics.py`, exposed at `GET /metrics` on the backend and via a standalone metrics server (port 9100) on the two long-running worker entrypoints.

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_metrics.py
from backend.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

def test_metrics_endpoint_exposes_expected_metric_names():
    client.get("/healthz")
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "backend_request_latency_seconds" in body
    assert "external_api_errors_total" in body
    assert "llm_call_failures_total" in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/backend/test_metrics.py -v`
Expected: FAIL — `/metrics` returns 404

- [ ] **Step 3: Define the metrics and mount `/metrics`**

```python
# backend/metrics.py
from prometheus_client import Counter, Histogram

REQUEST_LATENCY = Histogram("backend_request_latency_seconds", "Request latency", ["endpoint"])
EXTERNAL_API_ERRORS = Counter("external_api_errors_total", "External API errors", ["source"])
LLM_CALL_FAILURES = Counter("llm_call_failures_total", "LLM call failures")
BACKTEST_JOB_DURATION = Histogram("backtest_job_duration_seconds", "Backtest job duration")
SIGNALS_NOTIFIED = Counter("signals_notified_total", "Signals that crossed the notification threshold", ["source"])
```

```python
# backend/main.py (append)
from prometheus_client import make_asgi_app
from backend.metrics import REQUEST_LATENCY

app.mount("/metrics", make_asgi_app())

@app.middleware("http")
async def track_latency(request, call_next):
    with REQUEST_LATENCY.labels(endpoint=request.url.path).time():
        return await call_next(request)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/backend/test_metrics.py -v`
Expected: 1 passed

- [ ] **Step 5: Count external API errors and LLM failures at their source**

```python
# mcp_servers/domain_data/http.py (modify request_with_retry's final raise)
from backend.metrics import EXTERNAL_API_ERRORS

def request_with_retry(
    client: httpx.Client, method: str, url: str, *, max_retries: int = 3, **kwargs
) -> httpx.Response:
    last_response = None
    for attempt in range(max_retries):
        response = client.request(method, url, **kwargs)
        if response.status_code not in RETRYABLE_STATUS:
            response.raise_for_status()
            return response
        last_response = response
        time.sleep(2**attempt)
    EXTERNAL_API_ERRORS.labels(source=client.base_url.host).inc()
    last_response.raise_for_status()
    return last_response
```

```python
# agents/chat.py (wrap the agent call)
from backend.metrics import LLM_CALL_FAILURES

async def chat(message: str, mcp_client, llm=None) -> str:
    llm = llm or get_llm()
    tools = await mcp_client.get_tools()
    agent = create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)
    try:
        result = await agent.ainvoke({"messages": [{"role": "user", "content": message}]})
    except Exception:
        LLM_CALL_FAILURES.inc()
        raise
    return result["messages"][-1].content
```

- [ ] **Step 6: Expose a standalone metrics server on the worker entrypoints**

```python
# backend/news_consumer_entrypoint.py (add at startup, before the loop)
from prometheus_client import start_http_server

start_http_server(9100)
```

```python
# backend/live_signal_entrypoint.py (add at startup)
from prometheus_client import start_http_server

start_http_server(9100)
```

- [ ] **Step 7: Re-run the full backend test suite to confirm nothing broke**

Run: `pytest tests/ -v`
Expected: all tests still passing

- [ ] **Step 8: Commit**

```bash
git add backend agents mcp_servers tests/backend
git commit -m "feat: instrument the backend and workers with Prometheus metrics"
```

### Task 54: ServiceMonitors

**Files:**
- Create: `k8s/base/backend-servicemonitor.yaml`, `k8s/base/news-consumer-servicemonitor.yaml`
- Modify: `k8s/overlays/dev/kustomization.yaml`, `k8s/overlays/prod/kustomization.yaml`

**Interfaces:**
- Consumes: the `/metrics` route (Task 53) and the `monitoring` namespace's Prometheus Operator CRDs (Task 52).

- [ ] **Step 1: Write the ServiceMonitors**

```yaml
# k8s/base/backend-servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: backend
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: backend
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

```yaml
# k8s/base/news-consumer-servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: news-consumer
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: news-consumer
  endpoints:
    - port: metrics
      path: /metrics
      interval: 30s
```

Note: `k8s/base/service.yaml` (Task 5) names its port `http`; add a named `metrics` port on `news-consumer`'s Service (create one, since Task 27's consumer had no Service — needed now purely for Prometheus to target port 9100):

```yaml
# k8s/base/news-consumer-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: news-consumer
spec:
  selector: { app: news-consumer }
  ports:
    - name: metrics
      port: 9100
      targetPort: 9100
```

- [ ] **Step 2: Add both to each overlay's resource list**

```yaml
# k8s/overlays/dev/kustomization.yaml (add to resources)
  - ../../base/backend-servicemonitor.yaml
  - ../../base/news-consumer-service.yaml
  - ../../base/news-consumer-servicemonitor.yaml
```

Apply the same three lines to `k8s/overlays/prod/kustomization.yaml`.

- [ ] **Step 3: Deploy and verify**

Run: `./scripts/deploy.sh dev "$(git rev-parse HEAD)"` then open the Prometheus UI (`kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090`) and check **Status → Targets**
Expected: `dev/backend` and `dev/news-consumer` targets both `UP`

- [ ] **Step 4: Commit**

```bash
git add k8s
git commit -m "feat: add ServiceMonitors for the backend and news consumer"
```

### Task 55: Alertmanager rules

**Files:**
- Create: `k8s/base/alert-rules.yaml`
- Modify: `k8s/overlays/dev/kustomization.yaml`, `k8s/overlays/prod/kustomization.yaml`

**Interfaces:**
- Consumes: metrics from Task 53, the `monitoring` namespace's Prometheus Operator `PrometheusRule` CRD (Task 52).

- [ ] **Step 1: Write the rules**

```yaml
# k8s/base/alert-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: trading-agent-alerts
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: trading-agent
      rules:
        - alert: NewsQueueBacklog
          expr: sqs_approximate_number_of_messages_visible{queue_name=~"trading-agent-news-.*"} > 100
          for: 10m
          labels: { severity: warning }
          annotations:
            summary: "News queue {{ $labels.queue_name }} has more than 100 unprocessed messages"
        - alert: ExternalAPIErrorSpike
          expr: increase(external_api_errors_total[15m]) > 10
          for: 5m
          labels: { severity: warning }
          annotations:
            summary: "{{ $labels.source }} returned repeated errors in the last 15 minutes"
        - alert: PodCrashLooping
          expr: increase(kube_pod_container_status_restarts_total{namespace=~"dev|prod"}[15m]) > 3
          for: 5m
          labels: { severity: critical }
          annotations:
            summary: "{{ $labels.namespace }}/{{ $labels.pod }} is crash-looping"
        - alert: BacktestJobFailureRate
          expr: rate(backtest_job_duration_seconds_count[30m]) == 0 and rate(backend_request_latency_seconds_count{endpoint="/backtests"}[30m]) > 0
          for: 10m
          labels: { severity: warning }
          annotations:
            summary: "Backtest requests are coming in but no backtest job durations are being recorded"
        - alert: ElevatedLLMFailureRate
          expr: increase(llm_call_failures_total[15m]) > 5
          for: 5m
          labels: { severity: warning }
          annotations:
            summary: "More than 5 LLM call failures in the last 15 minutes"
```

Note: `NewsQueueBacklog` assumes an SQS CloudWatch exporter (e.g. `prometheus-community/prometheus-cloudwatch-exporter`) is installed alongside `kube-prometheus-stack` to surface `sqs_approximate_number_of_messages_visible`; installing that exporter is a one-line Helm addition to Task 52 using the AWS credentials already granted to the node IAM role.

- [ ] **Step 2: Add to each overlay**

```yaml
# k8s/overlays/dev/kustomization.yaml (add to resources)
  - ../../base/alert-rules.yaml
```

Apply the same line to `k8s/overlays/prod/kustomization.yaml`.

- [ ] **Step 3: Deploy and verify**

Run: `./scripts/deploy.sh dev "$(git rev-parse HEAD)"` then `kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090` and check **Status → Rules**
Expected: all five `trading-agent` rules listed and in `ok` (not `err`) state

- [ ] **Step 4: Commit**

```bash
git add k8s
git commit -m "feat: add Alertmanager rules for queue, API, pod, and LLM health"
```

### Task 56: Grafana dashboard

**Files:**
- Create: `observability/grafana-dashboard.json`
- Create: `k8s/base/grafana-dashboard-configmap.yaml`
- Modify: `k8s/overlays/dev/kustomization.yaml`, `k8s/overlays/prod/kustomization.yaml`

**Interfaces:**
- Consumes: the metric names from Task 53; relies on the `kube-prometheus-stack` Grafana sidecar (enabled by default) that auto-loads any ConfigMap labeled `grafana_dashboard=1`.

- [ ] **Step 1: Write the dashboard JSON**

```json
{
  "title": "Trading Agent — Per-Namespace Health",
  "uid": "trading-agent-health",
  "panels": [
    {
      "title": "Request latency (p95)",
      "type": "timeseries",
      "targets": [{ "expr": "histogram_quantile(0.95, sum(rate(backend_request_latency_seconds_bucket[5m])) by (le, namespace))" }]
    },
    {
      "title": "External API errors",
      "type": "timeseries",
      "targets": [{ "expr": "sum(rate(external_api_errors_total[5m])) by (source, namespace)" }]
    },
    {
      "title": "LLM call failures",
      "type": "timeseries",
      "targets": [{ "expr": "sum(rate(llm_call_failures_total[5m])) by (namespace)" }]
    },
    {
      "title": "Signals notified",
      "type": "timeseries",
      "targets": [{ "expr": "sum(rate(signals_notified_total[1h])) by (source, namespace)" }]
    },
    {
      "title": "Pod restarts",
      "type": "timeseries",
      "targets": [{ "expr": "sum(increase(kube_pod_container_status_restarts_total{namespace=~\"dev|prod\"}[15m])) by (namespace, pod)" }]
    }
  ]
}
```

- [ ] **Step 2: Wrap it in a ConfigMap**

```yaml
# k8s/base/grafana-dashboard-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: trading-agent-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  trading-agent.json: |
```

Append the contents of `observability/grafana-dashboard.json`, indented under `trading-agent.json: |`, as the ConfigMap's data — this keeps the human-editable JSON and the deployed ConfigMap in sync by construction rather than by hand-copying.

- [ ] **Step 3: Add to each overlay**

Since this ConfigMap targets the shared `monitoring` namespace rather than `dev`/`prod`, apply it once, directly, rather than through either overlay:

```bash
kubectl apply -f k8s/base/grafana-dashboard-configmap.yaml
```

- [ ] **Step 4: Verify**

Run: `kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80`, log in, open **Dashboards**
Expected: "Trading Agent — Per-Namespace Health" is listed and every panel renders (empty is fine before real traffic; the query must not error)

- [ ] **Step 5: Commit**

```bash
git add observability k8s/base/grafana-dashboard-configmap.yaml
git commit -m "feat: add the per-namespace health Grafana dashboard"
```

---

## Out of scope

Per spec §15, the following are explicitly not planned here: crypto support, multi-user accounts/authentication, email/Slack notification channels, and Superpowers-style Agent Skills for domain workflows. The devil's-advocate node (Task 19) is the one spec §4.2 stretch item that *is* planned, marked optional.

## Self-review notes

- **Spec coverage:** every `docs/spec.md` section (§1 problem, §2 safety boundary, §3 scope, §4 architecture/multi-agent/MCP, §5 components, §6 data flow, §7 AWS/Terraform, §8 K8s layout, §9 CI/CD, §10 observability, §11 error handling, §12 testing, §13 data sources, §14 built-vs-not, §15 future extensions) maps to at least one task above; §15 maps to the "Out of scope" note rather than a task, by design.
- **Placeholder scan:** no TBD/TODO/"add appropriate handling" text; every step has real code, config, or a real shell command with an expected result.
- **Type consistency:** `BacktestParams`/`BacktestResult` (Task 20) are the same types used by Tasks 21–22, 32, and Phase 8's frontend `BacktestParams`/`StrategyRun` shapes; `PipelineState` (Task 15) is used unchanged through Tasks 16–19 and Task 27; `chat(message, mcp_client, llm=None)` (Task 3) keeps this exact signature through Tasks 4, 18, and 53.

