type Verdict = { net_score?: number; confidence?: number; label?: string };
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

const RISK_LABELS: Record<string, string> = { low: "Low", medium: "Medium", high: "High" };

export function ResultsChart({
  verdict,
  bullClaims = [],
  bearClaims = [],
  riskLevel,
}: {
  verdict: Verdict;
  bullClaims?: Claim[];
  bearClaims?: Claim[];
  riskLevel?: string;
}) {
  const netScore = verdict.net_score ?? 0;
  const bullShare = Math.max(0, Math.min(100, 50 + netScore / 2));
  return (
    <div>
      <div className="results-section-label">Result</div>
      <div className="results-bar-row">
        <span className="results-bar-label results-bar-label-bear">Bear</span>
        <div className="results-bar-track">
          <div className="results-bar-bear" style={{ width: `${100 - bullShare}%` }} />
          <div className="results-bar-bull" style={{ width: `${bullShare}%` }} />
        </div>
        <span className="results-bar-label results-bar-label-bull">Bull</span>
      </div>
      {riskLevel && (
        <div className="results-risk">
          <div className="results-risk-label">Risk level</div>
          <div className="results-risk-badge-row">
            <span className={`results-risk-badge results-risk-${riskLevel}`}>
              {RISK_LABELS[riskLevel] ?? riskLevel}
            </span>
          </div>
        </div>
      )}
      <div className="results-cases">
        <div className="results-case">
          <div className="results-case-title results-case-title-bull">Bull case</div>
          {bullClaims.map((claim, i) => (
            <div className="results-case-item" key={i}>&bull; {claim.rationale}</div>
          ))}
        </div>
        <div className="results-case">
          <div className="results-case-title results-case-title-bear">Bear case</div>
          {bearClaims.map((claim, i) => (
            <div className="results-case-item" key={i}>&bull; {claim.rationale}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
