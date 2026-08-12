import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Watchlist } from "./Watchlist";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("Watchlist", () => {
  it("renders a row per watchlist symbol with a short verdict headline, confidence, and last-updated", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      {
        symbol: "AAPL", price: 150.25, percent_change: 1.2,
        verdict: { label: "Bullish, moderate confidence", confidence: 71 },
        last_updated: "2026-01-05T12:00:00+00:00",
      },
    ]);
    render(<Watchlist />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText(/Bullish/)).toBeInTheDocument();
    expect(screen.getByText(/71%/)).toBeInTheDocument();
  });

  it("shows the watchlist count out of the 30-symbol cap", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      { symbol: "AAPL", price: null, percent_change: null, verdict: {}, last_updated: null },
    ]);
    render(<Watchlist />);
    await waitFor(() => expect(screen.getByText("(1/30)")).toBeInTheDocument());
  });

  it("clicking a row opens the detail modal for that symbol", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      {
        symbol: "AAPL", price: 150.25, percent_change: 1.2,
        verdict: { label: "Bullish, moderate confidence", confidence: 71 }, last_updated: null,
      },
    ]);
    vi.mocked(apiClient.getSymbolDetail).mockResolvedValue({ symbol: "AAPL", agents: {}, verdict: {} });
    render(<Watchlist />);
    await waitFor(() => screen.getByText("AAPL"));
    fireEvent.click(screen.getByText("AAPL"));
    await waitFor(() => expect(screen.getByTestId("modal-backdrop")).toBeInTheDocument());
  });

  it("clicking remove calls apiClient.removeSymbol without opening the detail modal", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      { symbol: "AAPL", price: null, percent_change: null, verdict: { label: "Bullish" }, last_updated: null },
    ]);
    vi.mocked(apiClient.removeSymbol).mockResolvedValue(undefined);
    render(<Watchlist />);
    await waitFor(() => screen.getByText("AAPL"));
    fireEvent.click(screen.getByLabelText(/remove AAPL/i));
    await waitFor(() => expect(apiClient.removeSymbol).toHaveBeenCalledWith("AAPL"));
    expect(screen.queryByTestId("modal-backdrop")).not.toBeInTheDocument();
  });
});
