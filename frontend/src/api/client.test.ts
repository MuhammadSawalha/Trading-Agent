import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiClient } from "./client";

beforeEach(() => {
  global.fetch = vi.fn();
});

describe("apiClient", () => {
  it("getWatchlistDashboard calls the correct endpoint", async () => {
    (global.fetch as any).mockResolvedValue({ ok: true, json: async () => [{ symbol: "AAPL" }] });
    const result = await apiClient.getWatchlistDashboard();
    expect(global.fetch).toHaveBeenCalledWith("/api/dashboards/watchlist");
    expect(result).toEqual([{ symbol: "AAPL" }]);
  });

  it("addSymbol POSTs to /api/watchlist/{symbol} and throws on 422", async () => {
    (global.fetch as any).mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: "invalid" }) });
    await expect(apiClient.addSymbol("BAD")).rejects.toThrow("invalid");
  });
});
