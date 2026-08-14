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

const SPECIALISTS = ["Fundamentals", "Technical", "Sentiment", "Macro_Options"];
// Strictly sequential from Bull onward — confirmed against
// services/scheduler/src/graph/build_graph.py: add_edge("bull", "bear"),
// add_edge("bear", "risk"), add_edge("risk", "manager"). Bear's rebuttal
// round requires seeing Bull's specific claims, so this was never actually
// parallel despite docs/spec.md §4.3's header wording.
const SEQUENCE = ["Bull", "Bear", "Risk", "Manager"];

function Node({
  name,
  data,
  selected,
  onSelect,
}: {
  name: string;
  data: AgentData;
  selected: boolean;
  onSelect: (name: string) => void;
}) {
  return (
    <div
      data-testid={`agent-node-${name}`}
      onClick={() => onSelect(name)}
      className={`pipeline-node ${freshnessClass(data.last_updated)} ${selected ? "pipeline-node-selected" : ""}`}
    >
      <strong>{name.replace("_", "/")}</strong>
      <div className="pipeline-node-age">
        {data.last_updated ? new Date(data.last_updated as string).toLocaleTimeString() : "never run"}
      </div>
    </div>
  );
}

export function PipelineView({
  agents,
  selected,
  onSelectNode,
}: {
  agents: Record<string, AgentData>;
  selected: string | null;
  onSelectNode: (name: string) => void;
}) {
  return (
    <div className="pipeline-view">
      <div className="pipeline-specialists">
        {SPECIALISTS.map((name) => (
          <Node key={name} name={name} data={agents[name] ?? {}} selected={selected === name} onSelect={onSelectNode} />
        ))}
      </div>
      <div className="pipeline-converge" aria-hidden="true">
        <svg width="100%" height="24" viewBox="0 0 400 24">
          <polyline points="50,0 50,12 200,12" fill="none" stroke="#3b4a6b" strokeWidth="1.5" />
          <polyline points="150,0 150,8 200,8" fill="none" stroke="#3b4a6b" strokeWidth="1.5" />
          <polyline points="250,0 250,8 200,8" fill="none" stroke="#3b4a6b" strokeWidth="1.5" />
          <polyline points="350,0 350,12 200,12" fill="none" stroke="#3b4a6b" strokeWidth="1.5" />
          <line x1="200" y1="6" x2="200" y2="20" stroke="#3b4a6b" strokeWidth="1.5" />
          <polygon points="200,24 195,16 205,16" fill="#3b4a6b" />
        </svg>
      </div>
      {SEQUENCE.map((name, i) => (
        <div key={name}>
          <Node name={name} data={agents[name] ?? {}} selected={selected === name} onSelect={onSelectNode} />
          {i < SEQUENCE.length - 1 && <div className="pipeline-arrow" aria-hidden="true">&#8595;</div>}
        </div>
      ))}
    </div>
  );
}
