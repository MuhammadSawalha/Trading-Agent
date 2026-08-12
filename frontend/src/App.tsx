import "./App.css";
import { DiscoveryGrid } from "./components/DiscoveryGrid";
import { Watchlist } from "./components/Watchlist";
import { ChatPanel } from "./components/ChatPanel";
import { NewsFeed } from "./components/NewsFeed";

export default function App() {
  return (
    <div style={{ display: "flex", width: "100%", height: "100vh" }}>
      <a href="/visualizer">Open live pipeline visualizer</a>
      <div style={{ width: "50%", overflowY: "auto", padding: "1rem" }}>
        <DiscoveryGrid />
        <Watchlist />
      </div>
      <div style={{ width: "50%", overflowY: "auto", padding: "1rem" }}>
        <ChatPanel />
        <NewsFeed />
      </div>
    </div>
  );
}
