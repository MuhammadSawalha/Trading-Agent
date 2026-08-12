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
  getDiscoveryDashboards: () => request<Record<string, { results: unknown[] }>>("/dashboards/discovery"),
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
