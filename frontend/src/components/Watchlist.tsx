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
