type Verdict = { net_score?: number; confidence?: number; label?: string };

export function ResultsChart({ verdict }: { verdict: Verdict }) {
  const netScore = verdict.net_score ?? 0;
  return (
    <div>
      <h3>{verdict.label ?? "No verdict yet"}</h3>
      <div style={{ width: "100%", background: "#eee", height: "1rem" }}>
        <div
          style={{
            width: `${Math.abs(netScore) / 2}%`,
            marginLeft: netScore >= 0 ? "50%" : `${50 - Math.abs(netScore) / 2}%`,
            background: netScore >= 0 ? "green" : "red",
            height: "1rem",
          }}
        />
      </div>
      <p>Confidence: {verdict.confidence ?? 0}%</p>
    </div>
  );
}
