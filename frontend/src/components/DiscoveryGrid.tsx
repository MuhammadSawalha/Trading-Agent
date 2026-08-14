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
    // relative_volume_10d_calc is already a percentage-of-average (e.g. 190.8 means "190.8%
    // of the 10-day average volume", i.e. ~1.9x) -- labeling it "×" would read as a 190x spike.
    metricKeys: ["relative_volume_10d_calc", "breakout_ratio", "volume_ratio", "ratio"],
    formatMetric: (v) => `${Number(v).toFixed(0)}% avg`,
  },
};
const PANEL_ORDER = ["top_gainers", "top_losers", "top_volume", "volume_breakout"];
const MAX_VISIBLE_ROWS = 3;
const DISPLAY_CAP = 10;
const SYMBOL_KEYS = ["symbol", "ticker"];
const PRICE_KEYS = ["price", "last_price", "close"];

// tradingview-mcp nests each row's price/volume/indicator fields under "indicators";
// stock-scanner-mcp nests them under "data". Neither is a flat row, so field lookups need to
// see through whichever wrapper (if any) a given row actually has.
function flattenRow(row: unknown): Record<string, unknown> {
  if (typeof row !== "object" || row === null) return {};
  const record = row as Record<string, unknown>;
  const nested = record.indicators ?? record.data;
  if (typeof nested === "object" && nested !== null) {
    return { ...record, ...(nested as Record<string, unknown>) };
  }
  return record;
}

function pickField(row: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (row[key] !== undefined && row[key] !== null) return row[key];
  }
  return undefined;
}

// Every dashboard's shape is whatever its own MCP tool happens to return, unmodified by the
// backend: tradingview-mcp wraps its list as {"result": [...]} (singular), stock-scanner-mcp
// returns a bare array with no wrapper, and only the api-backend route's own "nothing cached
// yet" fallback uses {"results": [...]} (plural) -- so all three have to be handled here.
function extractResults(dashboard: unknown): unknown[] {
  if (Array.isArray(dashboard)) return dashboard;
  if (typeof dashboard === "object" && dashboard !== null) {
    const record = dashboard as Record<string, unknown>;
    if (Array.isArray(record.results)) return record.results;
    if (Array.isArray(record.result)) return record.result;
  }
  return [];
}

export function DiscoveryGrid({ onSymbolAdded }: { onSymbolAdded?: () => void } = {}) {
  const [dashboards, setDashboards] = useState<Record<string, unknown>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
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
          const capped = extractResults(dashboards[key]).slice(0, DISPLAY_CAP);
          const isExpanded = expanded[key] ?? false;
          const visible = isExpanded ? capped : capped.slice(0, MAX_VISIBLE_ROWS);
          const remaining = capped.length - visible.length;
          return (
            <div key={key} className="discovery-card">
              <div className="discovery-card-title">{config.title}</div>
              {visible.length === 0 && <div className="discovery-empty">No data yet</div>}
              {visible.map((rawRow, i) => {
                const row = flattenRow(rawRow);
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
              {remaining > 0 && (
                <button
                  type="button"
                  className="discovery-more"
                  onClick={() => setExpanded((e) => ({ ...e, [key]: true }))}
                >
                  +{remaining} more
                </button>
              )}
              {isExpanded && capped.length > MAX_VISIBLE_ROWS && (
                <button
                  type="button"
                  className="discovery-more"
                  onClick={() => setExpanded((e) => ({ ...e, [key]: false }))}
                >
                  Show less
                </button>
              )}
            </div>
          );
        })}
      </div>
      <div className="discovery-add">
        <div className="discovery-add-row">
          <input
            className="discovery-add-input"
            placeholder="Add a company by its ticker..."
            value={tickerInput}
            onChange={(e) => setTickerInput(e.target.value)}
          />
          <button className="discovery-add-button" onClick={handleAdd}>Add +</button>
        </div>
        {addError && <p className="discovery-add-error">{addError}</p>}
      </div>
    </div>
  );
}
