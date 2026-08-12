import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import { PipelineView } from "./PipelineView";
import { ResultsChart } from "./ResultsChart";
import "./DetailModal.css";

// Matches ResultsChart's Claim type exactly (not a narrowed subset) — this array is
// passed straight through to ResultsChart's bullClaims/bearClaims props below, and a
// narrower local shape here would be a real tsc error (missing required properties),
// not just a style inconsistency.
type Claim = {
  strength: "strong" | "moderate" | "weak";
  corroborated: boolean;
  flagged_unreliable: boolean;
  rebutted_undefended: boolean;
  source_type: "news" | "volume" | "other";
  rationale: string;
  news_hours_old?: number | null;
  news_is_primary_entity?: boolean | null;
  volume_ratio?: number | null;
  avg_volume?: number | null;
};
type AgentData = {
  last_updated?: string | null;
  claims?: Claim[];
  rationale?: string;
  risk_level?: string;
  label?: string;
  confidence?: number;
  [key: string]: unknown;
};

function NodeOutput({ name, data }: { name: string; data: AgentData }) {
  if (!data.last_updated) {
    return <div className="node-output-empty">Not run yet.</div>;
  }
  if (name === "Risk") {
    return (
      <div>
        <div className="node-output-item">Risk level: {data.risk_level ?? "—"}</div>
        {data.rationale && <div className="node-output-item">{data.rationale}</div>}
      </div>
    );
  }
  if (name === "Manager") {
    return (
      <div className="node-output-item">
        {data.label ?? "—"} ({Math.round(data.confidence ?? 0)}% confidence)
      </div>
    );
  }
  const claims = data.claims ?? [];
  if (claims.length === 0) return <div className="node-output-empty">No claims produced.</div>;
  return (
    <>
      {claims.map((c, i) => (
        <div className="node-output-item" key={i}>
          &bull; {c.rationale} <span className="node-output-strength">({c.strength})</span>
        </div>
      ))}
    </>
  );
}

export function DetailModal({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  // Kept as `Record<string, any>` (matching the original file), not `Record<string,
  // AgentData>`: apiClient.getSymbolDetail resolves to `agents: Record<string, unknown>`
  // (see frontend/src/api/client.ts), which isn't assignable to a Record<string, AgentData>
  // state setter. `any` is the deliberate boundary between the untyped API response and this
  // component's internal AgentData/Claim types — PipelineView/ResultsChart below still
  // receive and enforce those stricter types on the other side of that boundary.
  const [detail, setDetail] = useState<{ agents: Record<string, any>; verdict: any } | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => { apiClient.getSymbolDetail(symbol).then(setDetail); }, [symbol]);

  return (
    <div data-testid="modal-backdrop" onClick={onClose} className="modal-backdrop">
      <div onClick={(e) => e.stopPropagation()} className="modal-card">
        <div className="modal-header">
          <div className="modal-title">{symbol}</div>
          <div className="modal-close" onClick={onClose}>&times;</div>
        </div>
        {detail && (
          <>
            <div className="modal-section-label">Pipeline &middot; click a node for its output</div>
            <PipelineView agents={detail.agents} selected={selectedNode} onSelectNode={setSelectedNode} />
            {selectedNode && (
              <div className="node-output-panel">
                <div className="node-output-title">{selectedNode.replace("_", "/")} &middot; output</div>
                <NodeOutput name={selectedNode} data={detail.agents[selectedNode] ?? {}} />
              </div>
            )}
            <ResultsChart
              verdict={detail.verdict}
              bullClaims={detail.agents.Bull?.claims}
              bearClaims={detail.agents.Bear?.claims}
              riskLevel={detail.agents.Risk?.risk_level}
            />
            <div className="modal-footer">
              <div className="modal-verdict-label">{detail.verdict?.label ?? "No verdict yet"}</div>
              <div className="modal-footer-right">
                <div className="modal-confidence">{Math.round(detail.verdict?.confidence ?? 0)}%</div>
                <a
                  className="modal-watch-live"
                  href={`/visualizer.html?symbol=${symbol}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Watch live <span>&#8599;</span>
                </a>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
