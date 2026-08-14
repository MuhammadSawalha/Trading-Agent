import { useState } from "react";
import { useSSE } from "../hooks/useSSE";
import "./LiveVisualizer.css";

type PipelineEvent = { agent: string; status: "started" | "finished" | "failed"; timestamp: string; reason: string };

const NODE_ORDER = ["Fundamentals", "Technical", "Sentiment", "Macro_Options", "Bull", "Bear", "Risk", "Manager"];

function computeStates(events: PipelineEvent[]): Record<string, "idle" | "running" | "finished" | "failed"> {
  const states: Record<string, "idle" | "running" | "finished" | "failed"> = {};
  for (const node of NODE_ORDER) states[node] = "idle";
  for (const event of events) {
    states[event.agent] = event.status === "started" ? "running" : event.status === "failed" ? "failed" : "finished";
  }
  return states;
}

export function LiveVisualizer({ symbol }: { symbol: string }) {
  const { events } = useSSE<PipelineEvent>(`/symbols/${symbol}/stream`);
  const [selected, setSelected] = useState<string | null>(null);
  const states = computeStates(events);

  return (
    <div className="live-viz">
      <div className="live-viz-eyebrow">Live Pipeline</div>
      <h2 className="live-viz-symbol">{symbol}</h2>
      <div className="live-viz-nodes">
        {NODE_ORDER.map((node) => (
          <div
            key={node}
            data-testid={`viz-node-${node}`}
            onClick={() => setSelected(node)}
            className={`viz-node viz-${states[node]}`}
          >
            <div className="viz-node-name">{node.replace("_", "/")}</div>
            <div className="viz-node-state">
              {states[node]}
              {states[node] === "running" && "…"}
            </div>
          </div>
        ))}
      </div>
      {selected && (
        <pre className="live-viz-events">{JSON.stringify(events.filter((e) => e.agent === selected), null, 2)}</pre>
      )}
    </div>
  );
}
