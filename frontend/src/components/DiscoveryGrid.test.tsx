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

  it("reads results from tradingview-mcp's singular {result: [...]} shape", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { result: [{ symbol: "AAA", changePercent: 5 }] },
      top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("AAA")).toBeInTheDocument());
  });

  it("reads results from stock-scanner-mcp's bare-array shape (no wrapper at all)", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] },
      top_volume: [{ symbol: "BBB", volume: 123 }],
      volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("BBB")).toBeInTheDocument());
  });

  it("reads price and volume from tradingview-mcp's nested 'indicators' wrapper", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: {
        result: [{ symbol: "NASDAQ:TAOP", changePercent: 11.4, indicators: { close: 0.9242, volume: 111689 } }],
      },
      top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("$0.92")).toBeInTheDocument());
    expect(screen.getByText("+11.4%")).toBeInTheDocument();
  });

  it("reads price and the relative-volume metric from stock-scanner-mcp's nested 'data' wrapper", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] }, top_volume: { results: [] },
      volume_breakout: [
        { symbol: "NASDAQ:EGHA", data: { close: 10.3511, volume: 1660883, relative_volume_10d_calc: 190.8 } },
      ],
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("$10.35")).toBeInTheDocument());
    expect(screen.getByText("191% avg")).toBeInTheDocument();
  });

  it("caps a panel at 10 results and shows the true remaining count against that cap", async () => {
    const results = Array.from({ length: 25 }, (_, i) => ({ symbol: `SYM${i}`, changePercent: i }));
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { result: results },
      top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("+7 more")).toBeInTheDocument());
  });

  it("clicking '+N more' expands the panel to show the rest, up to the cap", async () => {
    const results = Array.from({ length: 25 }, (_, i) => ({ symbol: `SYM${i}`, changePercent: i }));
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { result: results },
      top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText("+7 more")).toBeInTheDocument());

    fireEvent.click(screen.getByText("+7 more"));
    expect(screen.getByText("SYM9")).toBeInTheDocument(); // 10th row (index 9), within the cap
    expect(screen.queryByText("SYM10")).not.toBeInTheDocument(); // beyond the cap
    expect(screen.getByText("Show less")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Show less"));
    expect(screen.queryByText("SYM9")).not.toBeInTheDocument();
    expect(screen.getByText("+7 more")).toBeInTheDocument();
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
