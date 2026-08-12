import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DiscoveryGrid } from "./DiscoveryGrid";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("DiscoveryGrid", () => {
  it("renders all four dashboard panels", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: ["AAPL"] }, top_losers: { results: [] },
      top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    render(<DiscoveryGrid />);
    await waitFor(() => expect(screen.getByText(/top gainers/i)).toBeInTheDocument());
    expect(screen.getByText(/top losers/i)).toBeInTheDocument();
    expect(screen.getByText(/top volume/i)).toBeInTheDocument();
    expect(screen.getByText(/volume breakout/i)).toBeInTheDocument();
  });

  it("submitting the add box calls apiClient.addSymbol", async () => {
    vi.mocked(apiClient.getDiscoveryDashboards).mockResolvedValue({
      top_gainers: { results: [] }, top_losers: { results: [] }, top_volume: { results: [] }, volume_breakout: { results: [] },
    });
    vi.mocked(apiClient.addSymbol).mockResolvedValue(undefined);
    render(<DiscoveryGrid />);
    fireEvent.change(screen.getByPlaceholderText(/add ticker/i), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByText(/add/i));
    await waitFor(() => expect(apiClient.addSymbol).toHaveBeenCalledWith("AAPL"));
  });
});
