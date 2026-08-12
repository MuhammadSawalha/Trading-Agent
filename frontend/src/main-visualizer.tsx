import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { LiveVisualizer } from "./components/LiveVisualizer";
import "./index.css";

function VisualizerEntry() {
  const initialSymbol = new URLSearchParams(window.location.search).get("symbol") ?? "";
  const [symbol, setSymbol] = useState(initialSymbol);
  const [input, setInput] = useState("");

  if (!symbol) {
    return (
      <div style={{ padding: "1rem" }}>
        <h2>Live Pipeline Visualizer</h2>
        <input placeholder="Enter ticker..." value={input} onChange={(e) => setInput(e.target.value)} />
        <button onClick={() => setSymbol(input.toUpperCase())}>View</button>
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
