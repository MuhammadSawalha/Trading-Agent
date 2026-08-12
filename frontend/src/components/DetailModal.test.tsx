import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DetailModal } from "./DetailModal";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("DetailModal", () => {
  it("renders agent nodes with freshness-based styling and closes on backdrop click", async () => {
    const now = new Date().toISOString();
    const hourAgo = new Date(Date.now() - 3600_000).toISOString();
    vi.mocked(apiClient.getSymbolDetail).mockResolvedValue({
      symbol: "AAPL",
      agents: {
        Sentiment: { last_updated: now, claims: [] },
        Fundamentals: { last_updated: hourAgo, claims: [] },
        Manager: { label: "Bullish, moderate confidence", net_score: 42, confidence: 60 },
      },
      verdict: { label: "Bullish, moderate confidence", net_score: 42, confidence: 60 },
    });
    const onClose = vi.fn();
    render(<DetailModal symbol="AAPL" onClose={onClose} />);
    await waitFor(() => expect(screen.getByText("Sentiment")).toBeInTheDocument());

    const sentimentNode = screen.getByTestId("agent-node-Sentiment");
    const fundamentalsNode = screen.getByTestId("agent-node-Fundamentals");
    expect(sentimentNode.className).not.toBe(fundamentalsNode.className);

    fireEvent.click(screen.getByTestId("modal-backdrop"));
    expect(onClose).toHaveBeenCalled();
  });

  it("clicking a pipeline node shows its real output", async () => {
    const now = new Date().toISOString();
    vi.mocked(apiClient.getSymbolDetail).mockResolvedValue({
      symbol: "AAPL",
      agents: {
        Sentiment: { last_updated: now, claims: [{ rationale: "New Reuters coverage", strength: "strong" }] },
        Fundamentals: { last_updated: now, claims: [] },
        Bull: { last_updated: now, claims: [] },
        Bear: { last_updated: now, claims: [] },
        Risk: { last_updated: now, risk_level: "medium", rationale: "Elevated volatility" },
        Manager: { last_updated: now, label: "Bullish, moderate confidence", confidence: 71 },
      },
      verdict: { label: "Bullish, moderate confidence", net_score: 42, confidence: 71 },
    });
    render(<DetailModal symbol="AAPL" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("agent-node-Sentiment")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("agent-node-Sentiment"));
    expect(screen.getByText(/New Reuters coverage/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("agent-node-Risk"));
    expect(screen.getByText(/Elevated volatility/)).toBeInTheDocument();
    expect(screen.getByText(/Risk level: medium/)).toBeInTheDocument();
  });

  it("shows a Watch Live link scoped to the symbol, opening in a new tab", async () => {
    vi.mocked(apiClient.getSymbolDetail).mockResolvedValue({
      symbol: "AAPL",
      agents: {},
      verdict: { label: "Bullish, moderate confidence", net_score: 10, confidence: 55 },
    });
    render(<DetailModal symbol="AAPL" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/watch live/i)).toBeInTheDocument());
    const link = screen.getByText(/watch live/i).closest("a");
    expect(link).toHaveAttribute("href", "/visualizer.html?symbol=AAPL");
    expect(link).toHaveAttribute("target", "_blank");
  });
});
