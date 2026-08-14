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
          <NewsFeed symbols={watchlistSymbols} />
        </div>
      </div>
    </div>
  );
}
