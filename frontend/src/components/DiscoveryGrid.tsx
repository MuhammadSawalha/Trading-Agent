import { useEffect, useState } from "react";
import { apiClient } from "../api/client";

const PANEL_TITLES: Record<string, string> = {
  top_gainers: "Top Gainers", top_losers: "Top Losers",
  top_volume: "Top Volume", volume_breakout: "Volume Breakout",
};

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
