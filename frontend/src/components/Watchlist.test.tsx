import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Watchlist } from "./Watchlist";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("Watchlist", () => {
  it("renders a row per watchlist symbol with verdict and last-updated", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      { symbol: "AAPL", price: 150.25, percent_change: 1.2, verdict: { label: "Bullish, moderate confidence" }, last_updated: "2026-01-05T12:00:00+00:00" },
    ]);
    render(<Watchlist />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText(/Bullish, moderate confidence/)).toBeInTheDocument();
  });

  it("clicking remove calls apiClient.removeSymbol", async () => {
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([
      { symbol: "AAPL", price: null, percent_change: null, verdict: { label: "Bullish" }, last_updated: null },
    ]);
    vi.mocked(apiClient.removeSymbol).mockResolvedValue(undefined);
    render(<Watchlist />);
    await waitFor(() => screen.getByText("AAPL"));
    fireEvent.click(screen.getByLabelText(/remove AAPL/i));
    await waitFor(() => expect(apiClient.removeSymbol).toHaveBeenCalledWith("AAPL"));
  });
});
