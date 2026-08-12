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
});
