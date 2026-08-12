# Frontend Visual Redesign — Design

## Motivation

Manual QA (the process built in Phase J / Task 39) surfaced that the frontend, while functionally complete per spec §8, ships with essentially no custom styling — `frontend/src/App.css`/`index.css` are still the unmodified Vite React scaffold defaults (`.counter`, `.hero`, `.vite`, `.framework`), plus a handful of freshness-color classes added later for the pipeline modal/visualizer. Every real component (`DiscoveryGrid`, `Watchlist`, `ChatPanel`, `NewsFeed`, `DetailModal`, `LiveVisualizer`) renders as bare, unstyled HTML. This slipped through every Phase I review because those reviews verified functional/type correctness (`vitest`/`tsc`), not visual completeness — nobody rendered it in a browser until manual QA did.

Separately, manual QA also surfaced two real functional bugs (not styling):
1. `ChatPanel.tsx`'s `send()` has no error handling — a failed `/chat` call leaves the user's message stuck with no reply and no error shown.
2. `docs/manual-qa-checklist.md`'s live-visualizer checklist item says "four specialists in parallel, then Bull/Bear in parallel, then Risk, then Manager" — inherited from a `docs/spec.md` §4.3 header that contradicts both the actual pipeline code (`services/scheduler/src/graph/build_graph.py`: `bull → bear → risk → manager`, strictly sequential) and that same spec section's own body text (Bear's rebuttal round requires seeing Bull's specific claims, which is only possible if Bull already finished).

This design covers a full visual redesign plus these two fixes. It does not cover backend changes, or acquiring real TradingView/Stock-Scanner MCP server instances (see Non-Goals).

## Goals

- A cohesive, professional dark-theme visual design across the entire frontend (main page, detail modal, standalone live visualizer), replacing the unstyled Vite-scaffold look.
- Fix the two real bugs found above.
- Everything continues to work against the real, already-existing backend endpoints and data shapes — no invented fields, no backend changes.

## Non-Goals

- **Backend changes.** The Manager verdict stays a single combined `net_score` (no separate Bull-total/Bear-total exposed); Risk stays a `low`/`medium`/`high` category (no numeric risk score). Confirmed with the user: match real data, don't add backend scope.
- **Getting the discovery dashboards (Top Gainers/Losers/Volume/Breakout) populated with real data.** That data comes exclusively from the two third-party MCP servers (TradingView MCP, Stock Scanner MCP), which spec.md explicitly says this project does not deploy. The current `.env` on the user's machine points at non-functional placeholder URLs. This design makes the empty state look intentional and handles whatever real data shape eventually arrives defensively (see Risks below) — it does not make that data appear.
- **`.env`/AWS credentials.** User-side local configuration, not a code change.

## Visual language

Dark theme, card-based, established through the brainstorming session's mockups (`.superpowers/brainstorm/9715-1786555447/content/full-design-v2.html` is the final approved reference):

- Background `#0d0f14`, cards `#161923` with `#262b3a` borders, `10px` radius.
- Text: primary `#e6e8ec`, muted `#8b93a7`/`#5c6479`, headings `#f1f3f8`.
- Semantic colors: bullish/positive `#3ddc84`, bearish/negative `#ff6b6b`, neutral `#9aa4bb`, volume/info `#8fb8ff`, breakout/warning `#ffb454`.
- Tabular numbers (`font-variant-numeric: tabular-nums`) for all price/volume/percent columns.
- Pill-shaped badges (`border-radius: 20px`) for verdict/risk labels, colored via the semantic palette at ~15% background opacity.

This palette should be implemented as CSS custom properties (extending the existing `--accent`/`--text`/`--bg` tokens in `index.css` rather than a parallel system), so component CSS references tokens, not hardcoded hex values.

## Components

### App.tsx (layout)

- Page title "Stock AI Analyzer" — centered, bold (~26px, weight 800), above both columns, replacing "Stock Research Agent" (which never existed in the UI before — it was implicit/untitled).
- Remove the top-of-page `<a href="/visualizer.html">Open live pipeline visualizer</a>` link entirely — see DetailModal below for its replacement.
- Two-column 50/50 layout retained (spec §8), restyled with the palette above.

### DiscoveryGrid.tsx

- Each of the 4 cards shows up to 3 real rows (symbol + relevant metric, colored per dashboard: green for gainers, red for losers, blue for volume, amber for breakout) plus a "+N more" line when the result set is larger.
- **Field-name risk (see Risks below):** render defensively. Try common reasonable key names for symbol/price/change/volume; if a result's shape doesn't match any known key, fall back to a minimal safe rendering (symbol-like field if found, else skip the row) rather than crashing the panel — one malformed/differently-shaped screener result must never blank the whole card. This replaces today's `JSON.stringify(r)` per-row dump.
- Empty state (`results: []`, which is what every discovery dashboard returns today with no real TradingView/Stock-Scanner data): a clean "No data yet" message, not a blank box.
- Ticker input placeholder text: "Add a company by its ticker..." (was "Add ticker...").
- Existing add-symbol error handling (inline error text) is retained as-is.

### Watchlist.tsx

- Table restyled per the mockup: `Sym / Price / Chg / Verdict / Age` columns, colored change (`+`green/`-`red), verdict pill combining `label` + confidence (`"Bullish · 71%"`), remove (`×`) button.
- **Fix:** the whole row becomes the click target for opening the detail modal (today only the symbol `<td>` is clickable) — matches the new header copy.
- Header row text: "Click any row for full analysis" (was "Click for pipeline").
- Panel header shows `(N/30)` count, matching spec §7's watchlist cap.

### ChatPanel.tsx

- Taller panel (460px vs. today's unconstrained/cramped height), scrollable message list, message bubbles right-aligned (user, accent-colored) / left-aligned (assistant, dark), wrapping naturally for long text (no fixed-width truncation).
- **Fix:** wrap the `apiClient.sendChatMessage` call in `try/catch`. On failure, append an inline error state to the message list (e.g., a distinctly-styled "Something went wrong — try again" entry) instead of silently leaving the user's message with no reply. Covered by a new test case (mock a rejected fetch, assert the error entry renders).

### NewsFeed.tsx

- Render newest-first (sort by `published_at` descending — today's list is unsorted, append-order-of-arrival).
- Show at least 5 items when at least 5 are available; cap the rendered list at a reasonable ceiling (20) to bound DOM growth, since `useSSE` accumulates events unboundedly and this list can only grow for the life of the page. (This also resolves a previously-deferred minor from Phase I's final review: "unbounded useSSE accumulation w/o dedup.")
- Each item: symbol + relative time-ago + headline, styled per the mockup.
- Note: confirmed against `services/api-backend/src/routers/stream.py` that a fresh SSE connection already backfills every currently-cached article per watchlist symbol on its first poll (`last_seen_uuids` starts empty), so "at least 5" is achievable on load whenever the watchlist has cached news — no backend change needed for this.

### DetailModal.tsx / PipelineView.tsx / ResultsChart.tsx

- Modal chrome: dark card, header shows `SYMBOL · $price +change%`, close (`×`).
- **Pipeline section, restructured to show real data flow** (per `build_graph.py`, confirmed sequential): the 4 specialist nodes render as before (freshness-colored per existing `agent-fresh`/`agent-recent`/`agent-stale`/`agent-never` thresholds: <5min/<30min/else/never — unchanged, just restyled), with a converging-arrow connector (SVG) into a full-width Bull node, then a down-arrow into Bear, then Risk, then Manager — sequential, not side-by-side, since side-by-side visually implies (incorrect) parallelism.
- **New: clicking any of the 8 nodes shows that node's real output** in an inline panel beneath the pipeline row:
  - Fundamentals/Technical/Sentiment/Macro_Options/Bull/Bear: their `claims` list (rationale + strength), same shape `ResultsChart` already renders for Bull/Bear — reused, not duplicated.
  - Risk: `rationale` + `risk_level`.
  - Manager: `label` + `confidence` (same summary already shown in the footer).
  - No data yet for that node (`agent-never`): "Not run yet."
- **Results section:** one Bull-vs-Bear bar built from `net_score` (split red/green at the actual ratio — no separate Bull/Bear numbers, confirmed non-goal above). "Risk level" label: bold, full-opacity, centered above a centered colored `low`/`medium`/`high` badge (was: plain text, right-aligned badge).
- Bull case / Bear case claim lists retained as today, restyled.
- Footer: Manager `label` + confidence `%`, plus a new **"Watch live ↗"** button — opens `/visualizer.html?symbol={symbol}` in a **new tab** (`target="_blank"`), replacing the old disconnected top-nav link with a contextual, symbol-scoped entry point.

### LiveVisualizer.tsx (standalone `visualizer.html` page)

- Restyled to match the dark theme: `idle` (dashed, muted), `running` (amber, pulsing — existing `viz-pulse` keyframe reused), `finished` (green), `failed` (red).
- Click-a-node-for-raw-events behavior unchanged (still the existing `JSON.stringify` dump), just restyled as a monospace block matching the theme. Improving that raw-JSON display into formatted output is out of scope for this pass — not requested, and it's a separate, self-contained enhancement if wanted later.

### docs/manual-qa-checklist.md fix

Correct the live-visualizer checklist line from "four specialists in parallel, then Bull/Bear in parallel, then Risk, then Manager" to "four specialists in parallel, then Bull, then Bear, then Risk, then Manager — each strictly sequential from Bull onward" (matches `build_graph.py`).

## Risks / assumptions

- **Discovery result field names are unknown.** TradingView MCP and Stock Scanner MCP are third-party servers with no schema documented anywhere in this repo, and the currently-configured URLs aren't real endpoints. `DiscoveryGrid`'s rendering of individual result rows is therefore a best-effort guess at reasonable field names (`symbol`, `price`, a change/volume metric), built defensively so an unexpected shape degrades gracefully instead of crashing. This will likely need a follow-up adjustment once real TradingView/Stock-Scanner endpoints exist and their actual response shape is known. Flagging this now so it isn't mistaken for a bug later.
- **Visual verification is manual.** `vitest`/`tsc` don't catch visual regressions (that's exactly the gap this whole redesign is fixing). The implementation plan should include actually running the dev server / `docker compose up` and checking it in a browser before calling this done — not just a green test suite.

## Testing strategy

- Existing component tests (`vitest` + RTL) continue to pass; update any assertions that depended on old copy text ("Click for pipeline", "Add ticker...") or DOM structure (row click target).
- New tests: `ChatPanel`'s error-handling path (rejected fetch → error entry renders); `DetailModal`/`PipelineView`'s click-node-for-output behavior (click a node, assert its claims/rationale render); `NewsFeed`'s sort-newest-first and cap behavior.
- `npm run build` must stay clean (`tsc -b` + `vite build`) — this is what caught the last cross-task type-drift issue in Phase I.
- Manual verification: run the stack (`docker compose up --build` or `npm run dev` against a running backend) and visually confirm against the approved mockup — this is the step that was skipped last time.
