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
    <div style={{ display: "flex", width: "100%", height: "100vh" }}>
      <a href="/visualizer.html">Open live pipeline visualizer</a>
      <div style={{ width: "50%", overflowY: "auto", padding: "1rem" }}>
        <DiscoveryGrid onSymbolAdded={() => setRefreshSignal((n) => n + 1)} />
        <Watchlist
          refreshSignal={refreshSignal}
          onRowsChange={(rows) => setWatchlistSymbols(rows.map((r) => r.symbol))}
        />
      </div>
      <div style={{ width: "50%", overflowY: "auto", padding: "1rem" }}>
        <ChatPanel symbols={watchlistSymbols} />
        <NewsFeed />
      </div>
    </div>
  );
}
