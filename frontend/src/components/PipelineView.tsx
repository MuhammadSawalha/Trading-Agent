type AgentData = { last_updated?: string | null; [key: string]: unknown };

const FRESHNESS_TIERS = [
  { maxAgeMs: 5 * 60_000, className: "agent-fresh" },      // < 5 min
  { maxAgeMs: 30 * 60_000, className: "agent-recent" },    // < 30 min
  { maxAgeMs: Infinity, className: "agent-stale" },
];

function freshnessClass(lastUpdated: string | null | undefined): string {
  if (!lastUpdated) return "agent-never";
  const ageMs = Date.now() - new Date(lastUpdated).getTime();
  return FRESHNESS_TIERS.find((t) => ageMs < t.maxAgeMs)!.className;
}

const PIPELINE_ORDER = ["Fundamentals", "Technical", "Sentiment", "Macro_Options", "Bull", "Bear", "Risk", "Manager"];

export function PipelineView({ agents }: { agents: Record<string, AgentData> }) {
  return (
    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
      {PIPELINE_ORDER.map((name) => {
        const data = agents[name] ?? {};
        return (
          <div key={name} data-testid={`agent-node-${name}`} className={freshnessClass(data.last_updated)}>
            <strong>{name}</strong>
            <div>{data.last_updated ? new Date(data.last_updated as string).toLocaleTimeString() : "never run"}</div>
          </div>
        );
      })}
    </div>
  );
}
