async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await (options ? fetch(`/api${path}`, options) : fetch(`/api${path}`));
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `request to ${path} failed with ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

type WatchlistVerdict = { label?: string; net_score?: number; confidence?: number };
type WatchlistRow = {
  symbol: string;
  price: number | null;
  percent_change: number | null;
  verdict: WatchlistVerdict;
  last_updated: string | null;
};

export const apiClient = {
  // Each dashboard's shape is whatever its underlying MCP tool happens to return, verbatim --
  // tradingview-mcp wraps its list as {"result": [...]} (singular), stock-scanner-mcp returns
  // a bare array with no wrapper at all, and only the "nothing cached yet" fallback in the
  // api-backend route actually uses {"results": [...]} (plural). See
  // DiscoveryGrid.tsx's extractResults for where all three get reconciled.
  getDiscoveryDashboards: () => request<Record<string, unknown>>("/dashboards/discovery"),
  getWatchlistDashboard: () => request<WatchlistRow[]>("/dashboards/watchlist"),
  getSymbolDetail: (symbol: string) => request<{ symbol: string; agents: Record<string, unknown>; verdict: unknown }>(`/symbols/${symbol}/detail`),
  addSymbol: (symbol: string) => request(`/watchlist/${symbol}`, { method: "POST" }),
  removeSymbol: (symbol: string) => request(`/watchlist/${symbol}`, { method: "DELETE" }),
  sendChatMessage: (question: string, symbols: string[]) =>
    request<{ answer: string }>("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, symbols }),
    }),
};
