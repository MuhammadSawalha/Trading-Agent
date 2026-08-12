import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import { PipelineView } from "./PipelineView";
import { ResultsChart } from "./ResultsChart";

export function DetailModal({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const [detail, setDetail] = useState<{ agents: Record<string, any>; verdict: any } | null>(null);

  useEffect(() => { apiClient.getSymbolDetail(symbol).then(setDetail); }, [symbol]);

  return (
    <div
      data-testid="modal-backdrop"
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div onClick={(e) => e.stopPropagation()} style={{ background: "white", width: "70%", maxHeight: "80%", overflowY: "auto", padding: "1rem" }}>
        <h2>{symbol}</h2>
        {detail && (
          <>
            <PipelineView agents={detail.agents} />
            <ResultsChart verdict={detail.verdict} />
          </>
        )}
      </div>
    </div>
  );
}
