import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DiscoveryGrid } from "./DiscoveryGrid";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("DiscoveryGrid", () => {
  it("renders all four dashboard panels", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] },
      top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText(/top gainers/i)).toBeInTheDocument());
    expect(screen.getByText(/top losers/i)).toBeInTheDocument();
    expect(screen.getByText(/top volume/i)).toBeInTheDocument();
    expect(screen.getByText(/volume breakout/i)).toBeInTheDocument();
  });

  it("shows an empty-state message when a panel has no results", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] },
      top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getAllByText(/no data yet/i)).toHaveLength(4));
  });

  it("shows up to 3 rows plus a '+N more' count when a panel has more results", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: {
        results: [
          { symbol: "AAA", price: 10, change_percent: 5 },
          { symbol: "BBB", price: 20, change_percent: 4 },
          { symbol: "CCC", price: 30, change_percent: 3 },
          { symbol: "DDD", price: 40, change_percent: 2 },
          { symbol: "EEE", price: 50, change_percent: 1 },
        ],
      },
      top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("AAA")).toBeInTheDocument());
    expect(screen.getByText("BBB")).toBeInTheDocument();
    expect(screen.getByText("CCC")).toBeInTheDocument();
    expect(screen.queryByText("DDD")).not.toBeInTheDocument();
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("skips a result row whose shape has no recognizable symbol field, without crashing", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [{ unexpected_field: "???" }, { symbol: "AAPL", change_percent: 2 }] },
      top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
  });

  it("submitting the add box calls apiClient.addSymbol", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    vi.mocked(apiClient.addSymbol).mockResolvedValue(undefined);
    render(<DiscoveryGrid />);
    fireEvent.change(screen.getByPlaceholderText(/add a company by its ticker/i), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByText(/add/i));
    await waitFor(() => expect(apiClient.addSymbol).toHaveBeenCalledWith("AAPL"));
  });
});
