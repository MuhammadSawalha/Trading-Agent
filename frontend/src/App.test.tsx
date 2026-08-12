import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import App from "./App";
import { apiClient } from "./api/client";
import { useSSE } from "./hooks/useSSE";

vi.mock("./api/client");
vi.mock("./hooks/useSSE");

describe("App", () => {
  it("renders the page title and no longer shows the old standalone visualizer link", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] },
      top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    vi.mocked(apiClient.getWatchlistDashboard).mockResolvedValue([]);
    vi.mocked(useSSE).mockReturnValue({ events: [] });

    render(<App />);

    expect(screen.getByText("Stock AI Analyzer")).toBeInTheDocument();
    expect(screen.queryByText(/open live pipeline visualizer/i)).not.toBeInTheDocument();
  });
});
