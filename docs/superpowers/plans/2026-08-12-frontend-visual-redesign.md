# Frontend Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the frontend's unstyled Vite-scaffold look with the approved dark, card-based design (`docs/superpowers/specs/2026-08-12-frontend-visual-redesign-design.md`), and fix the two real bugs manual QA found along the way (ChatPanel's missing error handling, and the manual QA checklist's wrong pipeline-dependency-order claim).

**Architecture:** A shared dark-theme token layer in `index.css` (extending the existing CSS custom properties), consumed by one CSS file per component. Each of the 5 leaf display components (DiscoveryGrid, Watchlist, ChatPanel, NewsFeed) gets its own task; the tightly-coupled detail-modal trio (DetailModal/PipelineView/ResultsChart) is one task since they share one visual unit and one new interaction (click-a-node); the standalone live visualizer is its own task since it's a separate page/bundle entry.

**Tech Stack:** React 19 + TypeScript, Vite 8, vitest + React Testing Library, plain CSS (no framework) via one stylesheet per component, following the codebase's existing `import "./X.css"` pattern (see `App.tsx`/`App.css`).

## Global Constraints

- Watchlist max: 30 symbols (spec §7) — the Selected Companies panel header must show `(N/30)`.
- Two-column layout, exactly 50/50 width split (spec §8) — already the case in `App.tsx`, preserved as-is.
- Pipeline nodes must be color-differentiated by freshness so a recently-updated agent is visually distinct from an older one (spec §8.1) — already implemented via the `agent-fresh`/`agent-recent`/`agent-stale`/`agent-never` classes in `PipelineView.tsx`; this plan restyles those classes, it does not change the freshness-tier logic (`< 5min` / `< 30min` / else / never, in `frontend/src/components/PipelineView.tsx`).
- No backend changes. The Manager verdict stays a single `net_score` (no separate Bull-total/Bear-total); Risk stays a `low`/`medium`/`high` category (no numeric score). Confirmed with the user during brainstorming — do not add fields to any backend response to make this easier.
- Discovery-dashboard row field names (from the third-party TradingView/Stock-Scanner MCP tools) are undocumented anywhere in this repo. Every task touching `DiscoveryGrid` must render defensively (unknown/missing fields degrade to "—" or a skipped row, never a crash) rather than assume a fixed schema is correct.

---

### Task 1: Dark design tokens, page title, and dead-CSS cleanup

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/App.css`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: CSS custom properties every later task consumes by name: `--bg`, `--panel-bg`, `--panel-border`, `--row-border`, `--text`, `--text-h`, `--text-muted`, `--text-dim`, `--positive`, `--negative`, `--neutral`, `--info`, `--warning`, `--accent`, `--accent-bg`. All defined once in `index.css`'s `:root` — later tasks must reference these by `var(--name)`, never redefine or hardcode the same hex values.
- Produces: `.app-title` class (used only in `App.tsx`).
- Removes: the old scaffold classes `.counter`, `.hero`, `.base`, `.framework`, `.vite`, `#center`, `#next-steps`, `#docs`, `#spacer`, `.ticks` from `App.css` — confirmed dead (grepped `frontend/src/components/*.tsx` for `className`/`class=`; none reference them).
- Removes: the `.viz-node`/`.viz-idle`/`.viz-running`/`.viz-finished`/`.viz-failed`/`@keyframes viz-pulse` rules from `App.css` — these are a **latent bug**: `App.css` is only imported by `App.tsx` (the `index.html` bundle), but `LiveVisualizer.tsx` (the only component using `viz-*` classes) is only ever rendered from `visualizer.html`'s separate entry (`main-visualizer.tsx`), which imports `index.css` but never `App.css`. These rules have never actually applied to anything. Task 7 reintroduces them correctly, in a stylesheet the visualizer page actually loads.

- [ ] **Step 1: Write the failing test for the new title and the removed old link**

```tsx
// frontend/src/App.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import App from "./App";
import { apiClient } from "./api/client";
import { useSSE } from "./hooks/useSSE";

vi.mock("./api/client");
vi.mock("./hooks/useSSE");

describe("App", () => {
  it("renders the page title and no longer shows the old standalone visualizer link", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] },
      top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([]);
    vi.mocked(useSSE).mockReturnValue({ events: [] });

    render(<App />);

    expect(screen.getByText("Stock AI Analyzer")).toBeInTheDocument();
    expect(screen.queryByText(/open live pipeline visualizer/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — `getByText("Stock AI Analyzer")` finds nothing (no such element yet).

- [ ] **Step 3: Rewrite `index.css`'s token layer**

Replace the full contents of `frontend/src/index.css` with:

```css
:root {
  --bg: #0d0f14;
  --panel-bg: #161923;
  --panel-border: #262b3a;
  --row-border: #1e2230;
  --text: #e6e8ec;
  --text-h: #f1f3f8;
  --text-muted: #8b93a7;
  --text-dim: #5c6479;
  --positive: #3ddc84;
  --negative: #ff6b6b;
  --neutral: #9aa4bb;
  --info: #8fb8ff;
  --warning: #ffb454;
  --accent: #5b8cff;
  --accent-bg: rgba(91, 140, 255, 0.15);

  --sans: system-ui, 'Segoe UI', Roboto, sans-serif;
  --mono: ui-monospace, Consolas, monospace;

  font: 15px/145% var(--sans);
  color-scheme: dark;
  color: var(--text);
  background: var(--bg);
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

#root {
  width: 100%;
  min-height: 100svh;
  box-sizing: border-box;
}

body {
  margin: 0;
}

h1, h2, h3 {
  font-family: var(--sans);
  font-weight: 600;
  color: var(--text-h);
  margin: 0;
}

p {
  margin: 0;
}
```

This is an intentional, permanent commitment to a single dark theme (matching the approved design) — it replaces the old scaffold's light-default-plus-`prefers-color-scheme`-override pattern rather than adding a third layer on top of it.

- [ ] **Step 4: Rewrite `App.css`**

Replace the full contents of `frontend/src/App.css` with:

```css
.app-title {
  text-align: center;
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--text-h);
  margin-bottom: 20px;
}

[class^="agent-"] {
  padding: 6px 8px;
  border-radius: 8px;
  min-width: 100px;
  font-size: 12px;
  cursor: pointer;
}

.agent-fresh {
  background: rgba(61, 220, 132, 0.12);
  border: 1px solid var(--positive);
}

.agent-recent {
  background: rgba(143, 184, 255, 0.10);
  border: 1px solid #3b4a6b;
}

.agent-stale {
  background: rgba(154, 164, 187, 0.08);
  border: 1px solid var(--panel-border);
  color: var(--text-dim);
}

.agent-never {
  background: var(--panel-bg);
  border: 1px dashed var(--text-dim);
  color: var(--text-dim);
}
```

- [ ] **Step 5: Update `App.tsx`**

Replace the full contents of `frontend/src/App.tsx` with:

```tsx
import { useState } from "react";
import "./App.css";
import { DiscoveryGrid } from "./components/DiscoveryGrid";
import { Watchlist } from "./components/Watchlist";
import { ChatPanel } from "./components/ChatPanel";
import { NewsFeed } from "./components/NewsFeed";

export default function App() {
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [watchlistSymbols, setWatchlistSymbols] = useState<string[]>([]);

  return (
    <div style={{ padding: "20px" }}>
      <h1 className="app-title">Stock AI Analyzer</h1>
      <div style={{ display: "flex", width: "100%", gap: "24px" }}>
        <div style={{ width: "50%", overflowY: "auto" }}>
          <DiscoveryGrid onSymbolAdded={() => setRefreshSignal((n) => n + 1)} />
          <Watchlist
            refreshSignal={refreshSignal}
            onRowsChange={(rows) => setWatchlistSymbols(rows.map((r) => r.symbol))}
          />
        </div>
        <div style={{ width: "50%", overflowY: "auto" }}>
          <ChatPanel symbols={watchlistSymbols} />
          <NewsFeed />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS

- [ ] **Step 7: Run the full test suite to check nothing else broke**

Run: `cd frontend && npx vitest run`
Expected: all currently-existing tests still pass (this task doesn't change any other component's markup/behavior, only tokens + `App.tsx`/`App.css`).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/index.css frontend/src/App.css frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "style: add dark design tokens and page title, drop dead Vite-scaffold CSS"
```

---

### Task 2: Discovery dashboard cards

**Files:**
- Modify: `frontend/src/components/DiscoveryGrid.tsx`
- Create: `frontend/src/components/DiscoveryGrid.css`
- Modify: `frontend/src/components/DiscoveryGrid.test.tsx`

**Interfaces:**
- Consumes: tokens from Task 1 (`var(--positive)`, `var(--negative)`, `var(--info)`, `var(--warning)`, `var(--panel-bg)`, `var(--panel-border)`, `var(--text)`, `var(--text-muted)`, `var(--text-dim)`, `var(--accent)`).
- Consumes: `apiClient.getDiscoveryDashboards(): Promise<Record<string, { results: unknown[] }>>` and `apiClient.addSymbol(symbol: string): Promise<unknown>` (both already exist in `frontend/src/api/client.ts`, unchanged).
- No new exports consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `frontend/src/components/DiscoveryGrid.test.tsx` with:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DiscoveryGrid } from "./DiscoveryGrid";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("DiscoveryGrid", () => {
  it("renders all four dashboard panels", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] },
      top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText(/top gainers/i)).toBeInTheDocument());
    expect(screen.getByText(/top losers/i)).toBeInTheDocument();
    expect(screen.getByText(/top volume/i)).toBeInTheDocument();
    expect(screen.getByText(/volume breakout/i)).toBeInTheDocument();
  });

  it("shows an empty-state message when a panel has no results", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] },
      top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getAllByText(/no data yet/i)).toHaveLength(4));
  });

  it("shows up to 3 rows plus a '+N more' count when a panel has more results", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: {
        results: [
          { symbol: "AAA", price: 10, change_percent: 5 },
          { symbol: "BBB", price: 20, change_percent: 4 },
          { symbol: "CCC", price: 30, change_percent: 3 },
          { symbol: "DDD", price: 40, change_percent: 2 },
          { symbol: "EEE", price: 50, change_percent: 1 },
        ],
      },
      top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("AAA")).toBeInTheDocument());
    expect(screen.getByText("BBB")).toBeInTheDocument();
    expect(screen.getByText("CCC")).toBeInTheDocument();
    expect(screen.queryByText("DDD")).not.toBeInTheDocument();
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("skips a result row whose shape has no recognizable symbol field, without crashing", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [{ unexpected_field: "???" }, { symbol: "AAPL", change_percent: 2 }] },
      top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
  });

  it("submitting the add box calls apiClient.addSymbol", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    vi.mocked(apiClient.addSymbol).mockResolvedValue(undefined);
    render(<DiscoveryGrid />);
    fireEvent.change(screen.getByPlaceholderText(/add a company by its ticker/i), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByText(/add/i));
    await waitFor(() => expect(apiClient.addSymbol).toHaveBeenCalledWith("AAPL"));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/DiscoveryGrid.test.tsx`
Expected: FAIL — the empty-state text, the 3-row cap, and the new placeholder text don't exist yet.

- [ ] **Step 3: Write `DiscoveryGrid.css`**

```css
.discovery-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 16px;
}

.discovery-card {
  background: var(--panel-bg);
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  padding: 12px;
}

.discovery-card-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}

.discovery-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  padding: 3px 0;
  font-variant-numeric: tabular-nums;
}

.discovery-row-price {
  color: var(--text);
}

.discovery-more {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 6px;
}

.discovery-empty {
  font-size: 12px;
  color: var(--text-dim);
}

.discovery-add {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.discovery-add-input {
  flex: 1;
  background: var(--panel-bg);
  border: 1px solid var(--panel-border);
  color: var(--text);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}

.discovery-add-button {
  background: var(--accent);
  border: none;
  color: white;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.discovery-add-error {
  color: var(--negative);
  font-size: 12px;
}
```

- [ ] **Step 4: Rewrite `DiscoveryGrid.tsx`**

Replace the full contents of `frontend/src/components/DiscoveryGrid.tsx` with:

```tsx
import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import "./DiscoveryGrid.css";

const PANEL_CONFIG: Record<
  string,
  { title: string; metricColor: string; metricKeys: string[]; formatMetric: (v: unknown) => string }
> = {
  top_gainers: {
    title: "Top Gainers",
    metricColor: "var(--positive)",
    metricKeys: ["change_percent", "percent_change", "changePercent"],
    formatMetric: (v) => `+${Number(v).toFixed(1)}%`,
  },
  top_losers: {
    title: "Top Losers",
    metricColor: "var(--negative)",
    metricKeys: ["change_percent", "percent_change", "changePercent"],
    formatMetric: (v) => `${Number(v).toFixed(1)}%`,
  },
  top_volume: {
    title: "Top Volume",
    metricColor: "var(--info)",
    metricKeys: ["volume", "relative_volume"],
    formatMetric: (v) => Number(v).toLocaleString(),
  },
  volume_breakout: {
    title: "Volume Breakout",
    metricColor: "var(--warning)",
    metricKeys: ["breakout_ratio", "volume_ratio", "ratio"],
    formatMetric: (v) => `${Number(v).toLocaleString()}×`,
  },
};
const PANEL_ORDER = ["top_gainers", "top_losers", "top_volume", "volume_breakout"];
const MAX_VISIBLE_ROWS = 3;
const SYMBOL_KEYS = ["symbol", "ticker"];
const PRICE_KEYS = ["price", "last_price", "close"];

function pickField(row: unknown, keys: string[]): unknown {
  if (typeof row !== "object" || row === null) return undefined;
  const record = row as Record<string, unknown>;
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) return record[key];
  }
  return undefined;
}

export function DiscoveryGrid({ onSymbolAdded }: { onSymbolAdded?: () => void } = {}) {
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
      onSymbolAdded?.();
    } catch (e) {
      setAddError((e as Error).message);
    }
  };

  return (
    <div>
      <div className="discovery-grid">
        {PANEL_ORDER.map((key) => {
          const config = PANEL_CONFIG[key];
          const results = dashboards[key]?.results ?? [];
          const visible = results.slice(0, MAX_VISIBLE_ROWS);
          const remaining = results.length - visible.length;
          return (
            <div key={key} className="discovery-card">
              <div className="discovery-card-title">{config.title}</div>
              {visible.length === 0 && <div className="discovery-empty">No data yet</div>}
              {visible.map((row, i) => {
                const symbol = pickField(row, SYMBOL_KEYS);
                if (symbol === undefined) return null;
                const price = pickField(row, PRICE_KEYS);
                const metric = pickField(row, config.metricKeys);
                return (
                  <div className="discovery-row" key={i}>
                    <span>{String(symbol)}</span>
                    {price !== undefined && (
                      <span className="discovery-row-price">${Number(price).toFixed(2)}</span>
                    )}
                    <span style={{ color: config.metricColor }}>
                      {metric !== undefined ? config.formatMetric(metric) : "—"}
                    </span>
                  </div>
                );
              })}
              {remaining > 0 && <div className="discovery-more">+{remaining} more</div>}
            </div>
          );
        })}
      </div>
      <div className="discovery-add">
        <input
          className="discovery-add-input"
          placeholder="Add a company by its ticker..."
          value={tickerInput}
          onChange={(e) => setTickerInput(e.target.value)}
        />
        <button className="discovery-add-button" onClick={handleAdd}>Add +</button>
        {addError && <p className="discovery-add-error">{addError}</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/DiscoveryGrid.test.tsx`
Expected: PASS (all 5 tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DiscoveryGrid.tsx frontend/src/components/DiscoveryGrid.css frontend/src/components/DiscoveryGrid.test.tsx
git commit -m "style: redesign discovery dashboard cards with real data and defensive rendering"
```

---

### Task 3: Watchlist table

**Files:**
- Modify: `frontend/src/components/Watchlist.tsx`
- Create: `frontend/src/components/Watchlist.css`
- Modify: `frontend/src/components/Watchlist.test.tsx`

**Interfaces:**
- Consumes: tokens from Task 1.
- Consumes: `apiClient.getWatchlistDashboard(): Promise<Row[]>` and `apiClient.removeSymbol(symbol: string): Promise<unknown>` (existing, unchanged). `Row` shape (from `frontend/src/api/client.ts`): `{ symbol: string; price: number | null; percent_change: number | null; verdict: { label?: string; net_score?: number; confidence?: number }; last_updated: string | null }`.
- Consumes: `DetailModal` from `./DetailModal` — props unchanged (`{ symbol: string; onClose: () => void }`), so this task has no dependency on Task 6 landing first.
- No new exports consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `frontend/src/components/Watchlist.test.tsx` with:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Watchlist } from "./Watchlist";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("Watchlist", () => {
  it("renders a row per watchlist symbol with a short verdict headline, confidence, and last-updated", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      {
        symbol: "AAPL", price: 150.25, percent_change: 1.2,
        verdict: { label: "Bullish, moderate confidence", confidence: 71 },
        last_updated: "2026-01-05T12:00:00+00:00",
      },
    ]);
    render(<Watchlist />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText(/Bullish/)).toBeInTheDocument();
    expect(screen.getByText(/71%/)).toBeInTheDocument();
  });

  it("shows the watchlist count out of the 30-symbol cap", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      { symbol: "AAPL", price: null, percent_change: null, verdict: {}, last_updated: null },
    ]);
    render(<Watchlist />);
    await waitFor(() => expect(screen.getByText("(1/30)")).toBeInTheDocument());
  });

  it("clicking a row opens the detail modal for that symbol", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      {
        symbol: "AAPL", price: 150.25, percent_change: 1.2,
        verdict: { label: "Bullish, moderate confidence", confidence: 71 }, last_updated: null,
      },
    ]);
    vi.mocked(apiClient.getSymbolDetail).mockResolvedValue({ symbol: "AAPL", agents: {}, verdict: {} });
    render(<Watchlist />);
    await waitFor(() => screen.getByText("AAPL"));
    fireEvent.click(screen.getByText("AAPL"));
    await waitFor(() => expect(screen.getByTestId("modal-backdrop")).toBeInTheDocument());
  });

  it("clicking remove calls apiClient.removeSymbol without opening the detail modal", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      { symbol: "AAPL", price: null, percent_change: null, verdict: { label: "Bullish" }, last_updated: null },
    ]);
    vi.mocked(apiClient.removeSymbol).mockResolvedValue(undefined);
    render(<Watchlist />);
    await waitFor(() => screen.getByText("AAPL"));
    fireEvent.click(screen.getByLabelText(/remove AAPL/i));
    await waitFor(() => expect(apiClient.removeSymbol).toHaveBeenCalledWith("AAPL"));
    expect(screen.queryByTestId("modal-backdrop")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/Watchlist.test.tsx`
Expected: FAIL — confidence isn't rendered, `(1/30)` doesn't exist, whole-row click isn't wired yet.

- [ ] **Step 3: Write `Watchlist.css`**

```css
.watchlist-panel {
  background: var(--panel-bg);
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  overflow: hidden;
}

.watchlist-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid var(--panel-border);
}

.watchlist-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-h);
}

.watchlist-count {
  color: var(--text-dim);
  font-weight: 400;
}

.watchlist-hint {
  font-size: 11px;
  color: var(--text-dim);
}

.watchlist-table {
  width: 100%;
  border-collapse: collapse;
}

.watchlist-row {
  cursor: pointer;
  font-size: 13px;
}

.watchlist-row td {
  padding: 8px 14px;
  border-top: 1px solid var(--row-border);
}

.watchlist-symbol {
  font-weight: 600;
}

.watchlist-price {
  font-variant-numeric: tabular-nums;
}

.watchlist-change-positive {
  color: var(--positive);
  font-variant-numeric: tabular-nums;
}

.watchlist-change-negative {
  color: var(--negative);
  font-variant-numeric: tabular-nums;
}

.watchlist-verdict-pill {
  border-radius: 20px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
}

.watchlist-verdict-positive {
  background: rgba(61, 220, 132, 0.15);
  color: var(--positive);
}

.watchlist-verdict-negative {
  background: rgba(255, 107, 107, 0.15);
  color: var(--negative);
}

.watchlist-verdict-neutral {
  background: rgba(139, 147, 167, 0.15);
  color: var(--neutral);
}

.watchlist-age {
  color: var(--text-muted);
  font-size: 12px;
}

.watchlist-remove {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 14px;
}
```

- [ ] **Step 4: Rewrite `Watchlist.tsx`**

Replace the full contents of `frontend/src/components/Watchlist.tsx` with:

```tsx
import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import { DetailModal } from "./DetailModal";
import "./Watchlist.css";

type Row = {
  symbol: string;
  price?: number | null;
  percent_change?: number | null;
  verdict: { label?: string; confidence?: number };
  last_updated: string | null;
};

const WATCHLIST_MAX = 30;

function verdictTone(label?: string): "positive" | "negative" | "neutral" {
  if (!label) return "neutral";
  const lower = label.toLowerCase();
  if (lower.includes("bullish")) return "positive";
  if (lower.includes("bearish")) return "negative";
  return "neutral";
}

function verdictHeadline(label?: string): string {
  if (!label) return "—";
  return label.split(",")[0];
}

export function Watchlist({
  refreshSignal = 0,
  onRowsChange,
}: {
  refreshSignal?: number;
  onRowsChange?: (rows: Row[]) => void;
} = {}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = () =>
    apiClient.getWatchlistDashboard().then((rows) => {
      setRows(rows);
      onRowsChange?.(rows);
    });
  useEffect(() => { refresh(); }, [refreshSignal]);

  return (
    <div className="watchlist-panel">
      <div className="watchlist-header">
        <div className="watchlist-title">
          Selected Companies <span className="watchlist-count">({rows.length}/{WATCHLIST_MAX})</span>
        </div>
        <div className="watchlist-hint">Click any row for full analysis</div>
      </div>
      <table className="watchlist-table">
        <tbody>
          {rows.map((row) => {
            const tone = verdictTone(row.verdict?.label);
            const changeClass =
              row.percent_change != null && row.percent_change < 0
                ? "watchlist-change-negative"
                : "watchlist-change-positive";
            return (
              <tr key={row.symbol} className="watchlist-row" onClick={() => setSelected(row.symbol)}>
                <td className="watchlist-symbol">{row.symbol}</td>
                <td className="watchlist-price">{row.price != null ? `$${row.price.toFixed(2)}` : "—"}</td>
                <td className={changeClass}>
                  {row.percent_change != null ? `${row.percent_change > 0 ? "+" : ""}${row.percent_change}%` : "—"}
                </td>
                <td>
                  <span className={`watchlist-verdict-pill watchlist-verdict-${tone}`}>
                    {verdictHeadline(row.verdict?.label)}
                    {row.verdict?.confidence != null && ` · ${row.verdict.confidence}%`}
                  </span>
                </td>
                <td className="watchlist-age">{row.last_updated ?? "never"}</td>
                <td>
                  <button
                    className="watchlist-remove"
                    aria-label={`remove ${row.symbol}`}
                    onClick={async (e) => {
                      e.stopPropagation();
                      await apiClient.removeSymbol(row.symbol);
                      refresh();
                    }}
                  >
                    ×
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {selected && <DetailModal symbol={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
```

Note the `e.stopPropagation()` in the remove button's click handler — without it, clicking remove would bubble up to the row's `onClick` and also open the detail modal, which the 4th test above catches.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/Watchlist.test.tsx`
Expected: PASS (all 4 tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Watchlist.tsx frontend/src/components/Watchlist.css frontend/src/components/Watchlist.test.tsx
git commit -m "style: redesign watchlist table with confidence badges and full-row click"
```

---

### Task 4: Chat panel redesign + fix missing error handling

**Files:**
- Modify: `frontend/src/components/ChatPanel.tsx`
- Create: `frontend/src/components/ChatPanel.css`
- Modify: `frontend/src/components/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: tokens from Task 1.
- Consumes: `apiClient.sendChatMessage(question: string, symbols: string[]): Promise<{ answer: string }>` (existing, unchanged).
- No new exports consumed by later tasks.

- [ ] **Step 1: Write the failing test for the error-handling fix**

Replace the full contents of `frontend/src/components/ChatPanel.test.tsx` with:

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

  it("shows an error message when sending fails, without losing the user's question", async () => {
    vi.mocked(apiClient.sendChatMessage).mockRejectedValue(new Error("network error"));
    render(<ChatPanel />);
    fireEvent.change(screen.getByPlaceholderText(/ask about your watchlist/i), { target: { value: "How does AAPL look?" } });
    fireEvent.click(screen.getByText(/send/i));
    await waitFor(() => expect(screen.getByText(/something went wrong/i)).toBeInTheDocument());
    expect(screen.getByText("How does AAPL look?")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `cd frontend && npx vitest run src/components/ChatPanel.test.tsx`
Expected: the first test PASSes (already-working behavior), the second FAILs — a rejected `sendChatMessage` currently throws unhandled and no "something went wrong" text ever appears.

- [ ] **Step 3: Write `ChatPanel.css`**

```css
.chat-panel {
  background: var(--panel-bg);
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  height: 460px;
}

.chat-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
}

.chat-messages {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
}

.chat-bubble {
  margin: 0;
  padding: 9px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.4;
  max-width: 85%;
  overflow-wrap: break-word;
}

.chat-bubble-user {
  align-self: flex-end;
  background: var(--accent);
  color: white;
  border-radius: 12px 12px 2px 12px;
}

.chat-bubble-assistant {
  align-self: flex-start;
  background: #20242f;
  color: var(--text);
  border-radius: 12px 12px 12px 2px;
}

.chat-bubble-error {
  align-self: flex-start;
  background: rgba(255, 107, 107, 0.15);
  color: var(--negative);
  border-radius: 12px 12px 12px 2px;
}

.chat-input-row {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.chat-input {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--panel-border);
  color: var(--text);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}

.chat-send {
  background: var(--panel-border);
  border: none;
  color: var(--text);
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
}
```

- [ ] **Step 4: Rewrite `ChatPanel.tsx`**

Replace the full contents of `frontend/src/components/ChatPanel.tsx` with:

```tsx
import { useState } from "react";
import { apiClient } from "../api/client";
import "./ChatPanel.css";

type Message = { role: "user" | "assistant" | "error"; text: string };

export function ChatPanel({ symbols = [] }: { symbols?: string[] } = {}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");

  const send = async () => {
    const question = input;
    setMessages((m) => [...m, { role: "user", text: question }]);
    setInput("");
    try {
      const { answer } = await apiClient.sendChatMessage(question, symbols);
      setMessages((m) => [...m, { role: "assistant", text: answer }]);
    } catch {
      setMessages((m) => [...m, { role: "error", text: "Something went wrong — try again." }]);
    }
  };

  return (
    <div className="chat-panel">
      <h2 className="chat-title">Chat</h2>
      <div className="chat-messages">
        {messages.map((m, i) => (
          <p key={i} className={`chat-bubble chat-bubble-${m.role}`}>{m.text}</p>
        ))}
      </div>
      <div className="chat-input-row">
        <input
          className="chat-input"
          placeholder="Ask about your watchlist..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="chat-send" onClick={send}>Send</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/ChatPanel.test.tsx`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx frontend/src/components/ChatPanel.css frontend/src/components/ChatPanel.test.tsx
git commit -m "fix: redesign chat panel and handle failed send requests"
```

---

### Task 5: News feed — newest-first, capped, styled

**Files:**
- Modify: `frontend/src/components/NewsFeed.tsx`
- Create: `frontend/src/components/NewsFeed.css`
- Create: `frontend/src/components/NewsFeed.test.tsx`

**Interfaces:**
- Consumes: tokens from Task 1.
- Consumes: `useSSE<T>(url: string): { events: T[] }` from `../hooks/useSSE` (existing, unchanged).
- No new exports consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

`NewsFeed` currently has no test file. Create `frontend/src/components/NewsFeed.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { NewsFeed } from "./NewsFeed";
import { useSSE } from "../hooks/useSSE";

vi.mock("../hooks/useSSE");

describe("NewsFeed", () => {
  it("renders articles newest-first", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [
        { symbol: "AAPL", uuid: "1", title: "Older article", published_at: "2026-01-01T00:00:00Z" },
        { symbol: "NVDA", uuid: "2", title: "Newer article", published_at: "2026-01-02T00:00:00Z" },
      ],
    });
    render(<NewsFeed />);
    const headlines = screen.getAllByText(/article/);
    expect(headlines[0]).toHaveTextContent("Newer article");
    expect(headlines[1]).toHaveTextContent("Older article");
  });

  it("caps the rendered list at 20 articles", () => {
    const events = Array.from({ length: 25 }, (_, i) => ({
      symbol: "AAPL",
      uuid: String(i),
      title: `Article ${i}`,
      published_at: `2026-01-01T00:00:${String(i).padStart(2, "0")}Z`,
    }));
    vi.mocked(useSSE).mockReturnValue({ events });
    render(<NewsFeed />);
    expect(screen.getAllByText(/^Article \d+$/)).toHaveLength(20);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/NewsFeed.test.tsx`
Expected: FAIL — today's `NewsFeed` renders events in arrival order with no cap.

- [ ] **Step 3: Write `NewsFeed.css`**

```css
.news-panel {
  background: var(--panel-bg);
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  padding: 14px;
}

.news-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.news-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--positive);
  display: inline-block;
}

.news-item {
  border-top: 1px solid var(--row-border);
  padding: 8px 0;
}

.news-item:first-child {
  border-top: none;
}

.news-item-header {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
}

.news-time {
  color: var(--text-dim);
  font-weight: 400;
  font-size: 11px;
}

.news-headline {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}
```

- [ ] **Step 4: Rewrite `NewsFeed.tsx`**

Replace the full contents of `frontend/src/components/NewsFeed.tsx` with:

```tsx
import { useSSE } from "../hooks/useSSE";
import "./NewsFeed.css";

type NewsEvent = {
  symbol: string;
  uuid?: string;
  title?: string;
  description?: string;
  published_at?: string;
  url?: string;
  source?: string;
};

const MAX_VISIBLE_ARTICLES = 20;

function timeAgo(publishedAt?: string): string {
  if (!publishedAt) return "";
  const ms = Date.now() - new Date(publishedAt).getTime();
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function NewsFeed() {
  const { events } = useSSE<NewsEvent>("/stream/news");
  const sorted = [...events]
    .sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""))
    .slice(0, MAX_VISIBLE_ARTICLES);

  return (
    <div className="news-panel">
      <h2 className="news-title">
        Latest news <span className="news-live-dot" />
      </h2>
      <div>
        {sorted.map((e, i) => (
          <div className="news-item" key={e.uuid ?? i}>
            <div className="news-item-header">
              <span>{e.symbol}</span>
              {e.published_at && <span className="news-time">{timeAgo(e.published_at)}</span>}
            </div>
            <div className="news-headline">
              {e.title ?? "(untitled)"}
              {e.source && ` — ${e.source}`}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/NewsFeed.test.tsx`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/NewsFeed.tsx frontend/src/components/NewsFeed.css frontend/src/components/NewsFeed.test.tsx
git commit -m "style: redesign news feed with newest-first sort and a display cap"
```

---

### Task 6: Detail modal — pipeline flow arrows, click-to-inspect nodes, real Bull/Bear/Risk display

**Files:**
- Modify: `frontend/src/components/DetailModal.tsx`
- Modify: `frontend/src/components/PipelineView.tsx`
- Modify: `frontend/src/components/ResultsChart.tsx`
- Create: `frontend/src/components/DetailModal.css`
- Modify: `frontend/src/components/DetailModal.test.tsx`

**Interfaces:**
- Consumes: tokens from Task 1.
- Consumes: `apiClient.getSymbolDetail(symbol: string): Promise<{ symbol: string; agents: Record<string, unknown>; verdict: unknown }>` (existing, unchanged).
- Produces: `PipelineView` now takes `{ agents: Record<string, AgentData>; selected: string | null; onSelectNode: (name: string) => void }` (was `{ agents }` only) — this is a breaking prop-signature change but `PipelineView` is only ever rendered from `DetailModal.tsx`, updated in this same task.
- Produces: `ResultsChart` now additionally takes `riskLevel?: string` and no longer renders the verdict label/confidence itself (moved to `DetailModal`'s footer) — again, only ever rendered from `DetailModal.tsx`, updated in this same task.
- Produces: `/visualizer.html?symbol={symbol}` as the URL convention the "Watch live" link uses — already supported by `frontend/src/main-visualizer.tsx` (reads `?symbol=` from `window.location.search`; confirmed by reading that file, no change needed there).

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `frontend/src/components/DetailModal.test.tsx` with:

```tsx
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

  it("clicking a pipeline node shows its real output", async () => {
    const now = new Date().toISOString();
    vi.mocked(apiClient.getSymbolDetail).mockResolvedValue({
      symbol: "AAPL",
      agents: {
        Sentiment: { last_updated: now, claims: [{ rationale: "New Reuters coverage", strength: "strong" }] },
        Fundamentals: { last_updated: now, claims: [] },
        Bull: { last_updated: now, claims: [] },
        Bear: { last_updated: now, claims: [] },
        Risk: { last_updated: now, risk_level: "medium", rationale: "Elevated volatility" },
        Manager: { last_updated: now, label: "Bullish, moderate confidence", confidence: 71 },
      },
      verdict: { label: "Bullish, moderate confidence", net_score: 42, confidence: 71 },
    });
    render(<DetailModal symbol="AAPL" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("agent-node-Sentiment")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("agent-node-Sentiment"));
    expect(screen.getByText(/New Reuters coverage/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("agent-node-Risk"));
    expect(screen.getByText(/Elevated volatility/)).toBeInTheDocument();
    expect(screen.getByText(/Risk level: medium/)).toBeInTheDocument();
  });

  it("shows a Watch Live link scoped to the symbol, opening in a new tab", async () => {
    vi.mocked(apiClient.getSymbolDetail).mockResolvedValue({
      symbol: "AAPL",
      agents: {},
      verdict: { label: "Bullish, moderate confidence", net_score: 10, confidence: 55 },
    });
    render(<DetailModal symbol="AAPL" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/watch live/i)).toBeInTheDocument());
    const link = screen.getByText(/watch live/i).closest("a");
    expect(link).toHaveAttribute("href", "/visualizer.html?symbol=AAPL");
    expect(link).toHaveAttribute("target", "_blank");
  });
});
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd frontend && npx vitest run src/components/DetailModal.test.tsx`
Expected: the first test PASSes (unchanged behavior), the other two FAIL — click-to-inspect and the Watch Live link don't exist yet.

- [ ] **Step 3: Write `DetailModal.css`**

```css
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-card {
  background: var(--panel-bg);
  border: 1px solid var(--panel-border);
  border-radius: 14px;
  width: 520px;
  max-width: 90vw;
  max-height: 85vh;
  overflow-y: auto;
  padding: 22px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.modal-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-h);
}

.modal-close {
  color: var(--text-dim);
  cursor: pointer;
  font-size: 18px;
}

.modal-section-label {
  font-size: 11px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 18px 0 8px;
}

.pipeline-view {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pipeline-specialists {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}

.pipeline-node {
  padding: 6px 8px;
  border-radius: 8px;
  font-size: 12px;
  cursor: pointer;
}

.pipeline-node-selected {
  box-shadow: 0 0 0 2px rgba(61, 220, 132, 0.25);
}

.pipeline-node-age {
  color: var(--text-dim);
  font-size: 11px;
}

.pipeline-converge {
  margin: 2px 0;
}

.pipeline-arrow {
  text-align: center;
  color: #3b4a6b;
  font-size: 14px;
  padding: 2px 0;
}

.node-output-panel {
  background: #12141b;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-top: 10px;
}

.node-output-title {
  font-size: 11px;
  color: var(--positive);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 6px;
  font-weight: 700;
}

.node-output-item {
  font-size: 12px;
  color: #c9cfdd;
  padding: 3px 0;
}

.node-output-strength {
  color: var(--text-dim);
}

.node-output-empty {
  font-size: 12px;
  color: var(--text-dim);
}

.results-section-label {
  font-size: 11px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 18px 0 8px;
}

.results-bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.results-bar-label {
  font-size: 12px;
  width: 40px;
}

.results-bar-label-bear {
  color: var(--negative);
}

.results-bar-label-bull {
  color: var(--positive);
  text-align: right;
}

.results-bar-track {
  flex: 1;
  height: 8px;
  background: #20242f;
  border-radius: 4px;
  overflow: hidden;
  display: flex;
}

.results-bar-bear {
  background: var(--negative);
}

.results-bar-bull {
  background: var(--positive);
}

.results-risk {
  margin-bottom: 14px;
}

.results-risk-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-h);
  text-align: center;
  margin-bottom: 6px;
}

.results-risk-badge-row {
  display: flex;
  justify-content: center;
}

.results-risk-badge {
  border-radius: 20px;
  padding: 3px 14px;
  font-size: 12px;
  font-weight: 700;
}

.results-risk-low {
  background: rgba(61, 220, 132, 0.15);
  color: var(--positive);
}

.results-risk-medium {
  background: rgba(255, 180, 84, 0.15);
  color: var(--warning);
}

.results-risk-high {
  background: rgba(255, 107, 107, 0.15);
  color: var(--negative);
}

.results-cases {
  display: flex;
  gap: 16px;
  font-size: 12px;
  margin-bottom: 16px;
}

.results-case {
  flex: 1;
}

.results-case-title {
  font-weight: 600;
  margin-bottom: 4px;
}

.results-case-title-bull {
  color: var(--positive);
}

.results-case-title-bear {
  color: var(--negative);
}

.results-case-item {
  color: #c9cfdd;
}

.modal-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid var(--panel-border);
  padding-top: 14px;
}

.modal-verdict-label {
  font-weight: 700;
  font-size: 15px;
  color: var(--text-h);
}

.modal-footer-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.modal-confidence {
  font-weight: 700;
  font-size: 18px;
}

.modal-watch-live {
  background: var(--panel-border);
  border: 1px solid #3b4a6b;
  color: var(--text);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12px;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
```

- [ ] **Step 4: Rewrite `PipelineView.tsx`**

Replace the full contents of `frontend/src/components/PipelineView.tsx` with:

```tsx
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

const SPECIALISTS = ["Fundamentals", "Technical", "Sentiment", "Macro_Options"];
// Strictly sequential from Bull onward — confirmed against
// services/scheduler/src/graph/build_graph.py: add_edge("bull", "bear"),
// add_edge("bear", "risk"), add_edge("risk", "manager"). Bear's rebuttal
// round requires seeing Bull's specific claims, so this was never actually
// parallel despite docs/spec.md §4.3's header wording.
const SEQUENCE = ["Bull", "Bear", "Risk", "Manager"];

function Node({
  name,
  data,
  selected,
  onSelect,
}: {
  name: string;
  data: AgentData;
  selected: boolean;
  onSelect: (name: string) => void;
}) {
  return (
    <div
      data-testid={`agent-node-${name}`}
      onClick={() => onSelect(name)}
      className={`pipeline-node ${freshnessClass(data.last_updated)} ${selected ? "pipeline-node-selected" : ""}`}
    >
      <strong>{name.replace("_", "/")}</strong>
      <div className="pipeline-node-age">
        {data.last_updated ? new Date(data.last_updated as string).toLocaleTimeString() : "never run"}
      </div>
    </div>
  );
}

export function PipelineView({
  agents,
  selected,
  onSelectNode,
}: {
  agents: Record<string, AgentData>;
  selected: string | null;
  onSelectNode: (name: string) => void;
}) {
  return (
    <div className="pipeline-view">
      <div className="pipeline-specialists">
        {SPECIALISTS.map((name) => (
          <Node key={name} name={name} data={agents[name] ?? {}} selected={selected === name} onSelect={onSelectNode} />
        ))}
      </div>
      <div className="pipeline-converge" aria-hidden="true">
        <svg width="100%" height="24" viewBox="0 0 400 24">
          <polyline points="50,0 50,12 200,12" fill="none" stroke="#3b4a6b" strokeWidth="1.5" />
          <polyline points="150,0 150,8 200,8" fill="none" stroke="#3b4a6b" strokeWidth="1.5" />
          <polyline points="250,0 250,8 200,8" fill="none" stroke="#3b4a6b" strokeWidth="1.5" />
          <polyline points="350,0 350,12 200,12" fill="none" stroke="#3b4a6b" strokeWidth="1.5" />
          <line x1="200" y1="6" x2="200" y2="20" stroke="#3b4a6b" strokeWidth="1.5" />
          <polygon points="200,24 195,16 205,16" fill="#3b4a6b" />
        </svg>
      </div>
      {SEQUENCE.map((name, i) => (
        <div key={name}>
          <Node name={name} data={agents[name] ?? {}} selected={selected === name} onSelect={onSelectNode} />
          {i < SEQUENCE.length - 1 && <div className="pipeline-arrow" aria-hidden="true">&#8595;</div>}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Rewrite `ResultsChart.tsx`**

Replace the full contents of `frontend/src/components/ResultsChart.tsx` with:

```tsx
type Verdict = { net_score?: number; confidence?: number; label?: string };
type Claim = {
  strength: "strong" | "moderate" | "weak";
  corroborated: boolean;
  flagged_unreliable: boolean;
  rebutted_undefended: boolean;
  source_type: "news" | "volume" | "other";
  rationale: string;
  news_hours_old?: number | null;
  news_is_primary_entity?: boolean | null;
  volume_ratio?: number | null;
  avg_volume?: number | null;
};

const RISK_LABELS: Record<string, string> = { low: "Low", medium: "Medium", high: "High" };

export function ResultsChart({
  verdict,
  bullClaims = [],
  bearClaims = [],
  riskLevel,
}: {
  verdict: Verdict;
  bullClaims?: Claim[];
  bearClaims?: Claim[];
  riskLevel?: string;
}) {
  const netScore = verdict.net_score ?? 0;
  const bullShare = Math.max(0, Math.min(100, 50 + netScore / 2));
  return (
    <div>
      <div className="results-section-label">Result</div>
      <div className="results-bar-row">
        <span className="results-bar-label results-bar-label-bear">Bear</span>
        <div className="results-bar-track">
          <div className="results-bar-bear" style={{ width: `${100 - bullShare}%` }} />
          <div className="results-bar-bull" style={{ width: `${bullShare}%` }} />
        </div>
        <span className="results-bar-label results-bar-label-bull">Bull</span>
      </div>
      {riskLevel && (
        <div className="results-risk">
          <div className="results-risk-label">Risk level</div>
          <div className="results-risk-badge-row">
            <span className={`results-risk-badge results-risk-${riskLevel}`}>
              {RISK_LABELS[riskLevel] ?? riskLevel}
            </span>
          </div>
        </div>
      )}
      <div className="results-cases">
        <div className="results-case">
          <div className="results-case-title results-case-title-bull">Bull case</div>
          {bullClaims.map((claim, i) => (
            <div className="results-case-item" key={i}>&bull; {claim.rationale}</div>
          ))}
        </div>
        <div className="results-case">
          <div className="results-case-title results-case-title-bear">Bear case</div>
          {bearClaims.map((claim, i) => (
            <div className="results-case-item" key={i}>&bull; {claim.rationale}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Rewrite `DetailModal.tsx`**

Replace the full contents of `frontend/src/components/DetailModal.tsx` with:

```tsx
import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import { PipelineView } from "./PipelineView";
import { ResultsChart } from "./ResultsChart";
import "./DetailModal.css";

// Matches ResultsChart's Claim type exactly (not a narrowed subset) — this array is
// passed straight through to ResultsChart's bullClaims/bearClaims props below, and a
// narrower local shape here would be a real tsc error (missing required properties),
// not just a style inconsistency.
type Claim = {
  strength: "strong" | "moderate" | "weak";
  corroborated: boolean;
  flagged_unreliable: boolean;
  rebutted_undefended: boolean;
  source_type: "news" | "volume" | "other";
  rationale: string;
  news_hours_old?: number | null;
  news_is_primary_entity?: boolean | null;
  volume_ratio?: number | null;
  avg_volume?: number | null;
};
type AgentData = {
  last_updated?: string | null;
  claims?: Claim[];
  rationale?: string;
  risk_level?: string;
  label?: string;
  confidence?: number;
  [key: string]: unknown;
};

function NodeOutput({ name, data }: { name: string; data: AgentData }) {
  if (!data.last_updated) {
    return <div className="node-output-empty">Not run yet.</div>;
  }
  if (name === "Risk") {
    return (
      <div>
        <div className="node-output-item">Risk level: {data.risk_level ?? "—"}</div>
        {data.rationale && <div className="node-output-item">{data.rationale}</div>}
      </div>
    );
  }
  if (name === "Manager") {
    return (
      <div className="node-output-item">
        {data.label ?? "—"} ({data.confidence ?? 0}% confidence)
      </div>
    );
  }
  const claims = data.claims ?? [];
  if (claims.length === 0) return <div className="node-output-empty">No claims produced.</div>;
  return (
    <>
      {claims.map((c, i) => (
        <div className="node-output-item" key={i}>
          &bull; {c.rationale} <span className="node-output-strength">({c.strength})</span>
        </div>
      ))}
    </>
  );
}

export function DetailModal({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  // Kept as `Record<string, any>` (matching the original file), not `Record<string,
  // AgentData>`: apiClient.getSymbolDetail resolves to `agents: Record<string, unknown>`
  // (see frontend/src/api/client.ts), which isn't assignable to a Record<string, AgentData>
  // state setter. `any` is the deliberate boundary between the untyped API response and this
  // component's internal AgentData/Claim types — PipelineView/ResultsChart below still
  // receive and enforce those stricter types on the other side of that boundary.
  const [detail, setDetail] = useState<{ agents: Record<string, any>; verdict: any } | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => { apiClient.getSymbolDetail(symbol).then(setDetail); }, [symbol]);

  return (
    <div data-testid="modal-backdrop" onClick={onClose} className="modal-backdrop">
      <div onClick={(e) => e.stopPropagation()} className="modal-card">
        <div className="modal-header">
          <div className="modal-title">{symbol}</div>
          <div className="modal-close" onClick={onClose}>&times;</div>
        </div>
        {detail && (
          <>
            <div className="modal-section-label">Pipeline &middot; click a node for its output</div>
            <PipelineView agents={detail.agents} selected={selectedNode} onSelectNode={setSelectedNode} />
            {selectedNode && (
              <div className="node-output-panel">
                <div className="node-output-title">{selectedNode.replace("_", "/")} &middot; output</div>
                <NodeOutput name={selectedNode} data={detail.agents[selectedNode] ?? {}} />
              </div>
            )}
            <ResultsChart
              verdict={detail.verdict}
              bullClaims={detail.agents.Bull?.claims}
              bearClaims={detail.agents.Bear?.claims}
              riskLevel={detail.agents.Risk?.risk_level}
            />
            <div className="modal-footer">
              <div className="modal-verdict-label">{detail.verdict?.label ?? "No verdict yet"}</div>
              <div className="modal-footer-right">
                <div className="modal-confidence">{detail.verdict?.confidence ?? 0}%</div>
                <a
                  className="modal-watch-live"
                  href={`/visualizer.html?symbol=${symbol}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Watch live <span>&#8599;</span>
                </a>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/DetailModal.test.tsx`
Expected: PASS (all 3 tests)

- [ ] **Step 8: Run the full test suite to check nothing else broke**

Run: `cd frontend && npx vitest run`
Expected: all tests across every component still pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/DetailModal.tsx frontend/src/components/PipelineView.tsx frontend/src/components/ResultsChart.tsx frontend/src/components/DetailModal.css frontend/src/components/DetailModal.test.tsx
git commit -m "feat: redesign detail modal with pipeline flow arrows and click-to-inspect node output"
```

---

### Task 7: Live pipeline visualizer restyle

**Files:**
- Modify: `frontend/src/components/LiveVisualizer.tsx`
- Modify: `frontend/src/main-visualizer.tsx`
- Create: `frontend/src/components/LiveVisualizer.css`

**Interfaces:**
- Consumes: tokens from Task 1 (this file is loaded on the `visualizer.html` bundle, which already imports `index.css` — confirmed in `main-visualizer.tsx`).
- Consumes: `useSSE<T>(url: string): { events: T[] }` (existing, unchanged).
- No behavior change to `computeStates` or the SSE event shape — purely visual, plus fixing the CSS-bundle gap noted in Task 1 (viz-* rules previously lived in `App.css`, which this page never loads).

- [ ] **Step 1: Confirm the existing test still describes the right behavior**

Read `frontend/src/components/LiveVisualizer.test.tsx` — it asserts on `textContent` containing `"finished"`/`"running"`/`"idle"` via `data-testid="viz-node-{name}"`, which this task preserves (only the internal markup structure changes, not the testids or the text content itself). No test file changes needed for this task; the existing test file remains valid as-is. Confirm by reading it before editing the component, so you can predict pass/fail without guessing.

- [ ] **Step 2: Run the existing test to establish the baseline**

Run: `cd frontend && npx vitest run src/components/LiveVisualizer.test.tsx`
Expected: PASS (this establishes the pre-change baseline you must not break)

- [ ] **Step 3: Write `LiveVisualizer.css`**

```css
.live-viz {
  background: var(--bg);
  color: var(--text);
  padding: 24px;
}

.live-viz-eyebrow {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 2px;
}

.live-viz-symbol {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 18px;
}

.live-viz-nodes {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.viz-node {
  padding: 10px 14px;
  border-radius: 8px;
  min-width: 100px;
  cursor: pointer;
  font-size: 13px;
}

.viz-node-name {
  font-weight: 600;
}

.viz-node-state {
  font-size: 11px;
  margin-top: 2px;
}

.viz-idle {
  background: var(--panel-bg);
  border: 1px dashed #3b4152;
  color: var(--text-dim);
}

.viz-running {
  background: rgba(255, 180, 84, 0.14);
  border: 1px solid var(--warning);
  color: #ffd9a0;
  animation: viz-pulse 1.2s ease-in-out infinite;
}

.viz-finished {
  background: rgba(61, 220, 132, 0.12);
  border: 1px solid var(--positive);
  color: #8fe6b0;
}

.viz-failed {
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid var(--negative);
  color: #ffb3b3;
}

@keyframes viz-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.live-viz-events {
  background: #12141b;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  padding: 12px 14px;
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text-muted);
  overflow-x: auto;
}

.live-viz-entry-form {
  padding: 24px;
  color: var(--text);
}

.live-viz-entry-input {
  background: var(--panel-bg);
  border: 1px solid var(--panel-border);
  color: var(--text);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  margin-right: 8px;
}

.live-viz-entry-button {
  background: var(--accent);
  border: none;
  color: white;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
```

- [ ] **Step 4: Rewrite `LiveVisualizer.tsx`**

Replace the full contents of `frontend/src/components/LiveVisualizer.tsx` with:

```tsx
import { useState } from "react";
import { useSSE } from "../hooks/useSSE";
import "./LiveVisualizer.css";

type PipelineEvent = { agent: string; status: "started" | "finished" | "failed"; timestamp: string; reason: string };

const NODE_ORDER = ["Fundamentals", "Technical", "Sentiment", "Macro_Options", "Bull", "Bear", "Risk", "Manager"];

function computeStates(events: PipelineEvent[]): Record<string, "idle" | "running" | "finished" | "failed"> {
  const states: Record<string, "idle" | "running" | "finished" | "failed"> = {};
  for (const node of NODE_ORDER) states[node] = "idle";
  for (const event of events) {
    states[event.agent] = event.status === "started" ? "running" : event.status === "failed" ? "failed" : "finished";
  }
  return states;
}

export function LiveVisualizer({ symbol }: { symbol: string }) {
  const { events } = useSSE<PipelineEvent>(`/symbols/${symbol}/stream`);
  const [selected, setSelected] = useState<string | null>(null);
  const states = computeStates(events);

  return (
    <div className="live-viz">
      <div className="live-viz-eyebrow">Live Pipeline</div>
      <h2 className="live-viz-symbol">{symbol}</h2>
      <div className="live-viz-nodes">
        {NODE_ORDER.map((node) => (
          <div
            key={node}
            data-testid={`viz-node-${node}`}
            onClick={() => setSelected(node)}
            className={`viz-node viz-${states[node]}`}
          >
            <div className="viz-node-name">{node.replace("_", "/")}</div>
            <div className="viz-node-state">
              {states[node]}
              {states[node] === "running" && "…"}
            </div>
          </div>
        ))}
      </div>
      {selected && (
        <pre className="live-viz-events">{JSON.stringify(events.filter((e) => e.agent === selected), null, 2)}</pre>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Update `main-visualizer.tsx`'s fallback form to use the new styling**

Replace the full contents of `frontend/src/main-visualizer.tsx` with:

```tsx
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { LiveVisualizer } from "./components/LiveVisualizer";
import "./index.css";
import "./components/LiveVisualizer.css";

function VisualizerEntry() {
  const initialSymbol = new URLSearchParams(window.location.search).get("symbol") ?? "";
  const [symbol, setSymbol] = useState(initialSymbol);
  const [input, setInput] = useState("");

  if (!symbol) {
    return (
      <div className="live-viz-entry-form">
        <h2>Live Pipeline Visualizer</h2>
        <input
          className="live-viz-entry-input"
          placeholder="Enter ticker..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button className="live-viz-entry-button" onClick={() => setSymbol(input.toUpperCase())}>View</button>
      </div>
    );
  }
  return <LiveVisualizer symbol={symbol} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <VisualizerEntry />
  </StrictMode>,
);
```

- [ ] **Step 6: Run test to verify it still passes**

Run: `cd frontend && npx vitest run src/components/LiveVisualizer.test.tsx`
Expected: PASS — same assertions as the Step 2 baseline, confirming the restyle didn't change observable behavior.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/LiveVisualizer.tsx frontend/src/components/LiveVisualizer.css frontend/src/main-visualizer.tsx
git commit -m "style: redesign live pipeline visualizer to match the new theme"
```

---

### Task 8: Fix manual QA checklist's pipeline dependency order

**Files:**
- Modify: `docs/manual-qa-checklist.md`

**Interfaces:**
- None — this is a standalone documentation fix, unrelated to any frontend code in Tasks 1-7.

- [ ] **Step 1: Fix the wrong dependency-order claim**

In `docs/manual-qa-checklist.md`, under "## Live pipeline visualizer", find this line:

```markdown
- [ ] Opening it for a symbol mid-run shows nodes transitioning idle → running → finished in the
      correct dependency order (four specialists in parallel, then Bull/Bear in parallel, then Risk, then Manager)
```

Replace it with:

```markdown
- [ ] Opening it for a symbol mid-run shows nodes transitioning idle → running → finished in the
      correct dependency order (four specialists in parallel, then Bull, then Bear, then Risk, then
      Manager — each strictly sequential from Bull onward, confirmed against
      services/scheduler/src/graph/build_graph.py)
```

This corrects a claim inherited from `docs/spec.md` §4.3's header ("Run in parallel"), which contradicts both the actual pipeline code (`build_graph.py`: `add_edge("bull", "bear")`, `add_edge("bear", "risk")`, strictly sequential) and that same spec section's own body text (Bear's rebuttal round requires seeing Bull's specific claims, which is only possible once Bull has already finished).

- [ ] **Step 2: Verify the file reads correctly**

Run: `grep -A2 "Live pipeline visualizer" docs/manual-qa-checklist.md`
Expected: the corrected line appears, no stray markdown formatting broken (checkbox syntax, indentation of the wrapped second line matches the file's existing style).

- [ ] **Step 3: Commit**

```bash
git add docs/manual-qa-checklist.md
git commit -m "docs: fix manual QA checklist's pipeline dependency order"
```

---

### Task 9: Full build and test verification

**Files:**
- None created or modified — this task is pure verification of Tasks 1-8's combined result.

**Interfaces:**
- None.

- [ ] **Step 1: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: every test file passes — `App.test.tsx`, `DiscoveryGrid.test.tsx`, `Watchlist.test.tsx`, `ChatPanel.test.tsx`, `NewsFeed.test.tsx`, `DetailModal.test.tsx`, `LiveVisualizer.test.tsx`, `client.test.ts` — output pristine (no unexpected warnings).

- [ ] **Step 2: Run the production build**

Run: `cd frontend && npm run build`
Expected: `tsc -b` reports zero type errors and `vite build` succeeds, producing both `dist/index.html` and `dist/visualizer.html` (two entries, per `vite.config.ts`'s `rollupOptions.input`). A type error here is the one class of bug none of the per-task test runs can catch (cross-file prop-shape drift), so this step is not optional even though every task's own tests already passed.

- [ ] **Step 3: Rebuild and restart the frontend container, if Docker is available**

Run: `docker compose up --build -d frontend`
Expected: the container builds and starts cleanly (check with `docker compose ps`). If Docker isn't available in this environment, skip this step and note it in the report — it isn't this task's job to install Docker.

- [ ] **Step 4: Report what a human needs to check manually**

Neither `vitest` nor `tsc` can catch a visual regression — that gap is exactly what this whole plan exists to close. In the task report, explicitly state: "Automated checks are clean; a human should open `http://localhost:3000` (and a detail-modal / `visualizer.html?symbol=X` view) in a browser and compare against the approved mockup at `.superpowers/brainstorm/9715-1786555447/content/full-design-v2.html` before this is considered visually verified." Do not claim the redesign "looks right" — only claim what was actually machine-checked.

- [ ] **Step 5: Commit**

Nothing to commit for this task (no files changed) — skip the commit step. If Step 1 or Step 2 fails, do not proceed to marking this task complete; report the failure instead.
