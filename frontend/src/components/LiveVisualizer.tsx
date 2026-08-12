import { useState } from "react";
import { useSSE } from "../hooks/useSSE";

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
    <div>
      <h2>Live Pipeline: {symbol}</h2>
      <div style={{ display: "flex", gap: "0.5rem" }}>
        {NODE_ORDER.map((node) => (
          <div
            key={node}
            data-testid={`viz-node-${node}`}
            onClick={() => setSelected(node)}
            className={`viz-node viz-${states[node]}`}
          >
            {node}: {states[node]}
          </div>
        ))}
      </div>
      {selected && <pre>{JSON.stringify(events.filter((e) => e.agent === selected), null, 2)}</pre>}
    </div>
  );
}
