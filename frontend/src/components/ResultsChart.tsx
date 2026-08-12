type Verdict = { net_score?: number; confidence?: number; label?: string };
type Claim = unknown;

export function ResultsChart({
  verdict,
  bullClaims = [],
  bearClaims = [],
}: {
  verdict: Verdict;
  bullClaims?: Claim[];
  bearClaims?: Claim[];
}) {
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
      <div style={{ display: "flex", gap: "1rem" }}>
        <div>
          <h4>Bull case</h4>
          <ul>
            {bullClaims.map((claim, i) => (
              <li key={i}>{String(claim)}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Bear case</h4>
          <ul>
            {bearClaims.map((claim, i) => (
              <li key={i}>{String(claim)}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
