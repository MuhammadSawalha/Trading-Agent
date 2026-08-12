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
