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
