import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { LiveVisualizer } from "./components/LiveVisualizer";
import "./index.css";
import "./components/LiveVisualizer.css";

function VisualizerEntry() {
  const initialSymbol = new URLSearchParams(window.location.search).get("symbol") ?? "";
  const [symbol, setSymbol] = useState(initialSymbol);
  const [input, setInput] = useState("");

  if (!symbol) {
    return (
      <div className="live-viz-entry-form">
        <h2>Live Pipeline Visualizer</h2>
        <input
          className="live-viz-entry-input"
          placeholder="Enter ticker..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button className="live-viz-entry-button" onClick={() => setSymbol(input.toUpperCase())}>View</button>
      </div>
    );
  }
  return <LiveVisualizer symbol={symbol} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <VisualizerEntry />
  </StrictMode>,
);
