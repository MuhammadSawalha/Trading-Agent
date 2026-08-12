import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import { DetailModal } from "./DetailModal";

type Row = {
  symbol: string;
  price?: number | null;
  percent_change?: number | null;
  verdict: { label?: string };
  last_updated: string | null;
};

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
    <div>
      <h2>Selected Companies</h2>
      <table>
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol}>
              <td onClick={() => setSelected(row.symbol)} style={{ cursor: "pointer" }}>{row.symbol}</td>
              <td>{row.price ?? "—"}</td>
              <td>{row.percent_change != null ? `${row.percent_change}%` : "—"}</td>
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
