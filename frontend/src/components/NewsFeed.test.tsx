import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { NewsFeed } from "./NewsFeed";
import { useSSE } from "../hooks/useSSE";

vi.mock("../hooks/useSSE");

// All fixtures anchor to "now" so they stay inside the feed's 23h recency window
// regardless of when the suite runs.
function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
}

describe("NewsFeed", () => {
  it("renders articles newest-first", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [
        { symbol: "AAPL", uuid: "1", title: "Older article", published_at: hoursAgo(5) },
        { symbol: "NVDA", uuid: "2", title: "Newer article", published_at: hoursAgo(1) },
      ],
    });
    render(<NewsFeed />);
    const headlines = screen.getAllByText(/article/);
    expect(headlines[0]).toHaveTextContent("Newer article");
    expect(headlines[1]).toHaveTextContent("Older article");
  });

  it("dedups events sharing the same uuid (e.g. after an SSE reconnect replays cached articles)", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [
        { symbol: "AAPL", uuid: "1", title: "Original article", published_at: hoursAgo(1) },
        { symbol: "AAPL", uuid: "1", title: "Original article", published_at: hoursAgo(1) },
      ],
    });
    render(<NewsFeed />);
    expect(screen.getAllByText(/Original article/)).toHaveLength(1);
  });

  it("hides articles for a symbol that's since been removed from the watchlist", () => {
    // The SSE connection's `events` only ever grows -- an article for MSFT stays in it even
    // after MSFT is removed, since the backend has no way to retract an already-sent event.
    // Passing the current watchlist is what lets the feed drop it from view.
    vi.mocked(useSSE).mockReturnValue({
      events: [
        { symbol: "MSFT", uuid: "1", title: "Azure article", published_at: hoursAgo(1) },
        { symbol: "GOOG", uuid: "2", title: "Google article", published_at: hoursAgo(1) },
      ],
    });
    render(<NewsFeed symbols={["GOOG"]} />);
    expect(screen.queryByText(/Azure article/)).not.toBeInTheDocument();
    expect(screen.getByText(/Google article/)).toBeInTheDocument();
  });

  it("shows every article when no symbols filter is provided", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [{ symbol: "MSFT", uuid: "1", title: "Azure article", published_at: hoursAgo(1) }],
    });
    render(<NewsFeed />);
    expect(screen.getByText(/Azure article/)).toBeInTheDocument();
  });

  it("caps the rendered list at 20 articles", () => {
    const events = Array.from({ length: 25 }, (_, i) => ({
      symbol: "AAPL",
      uuid: String(i),
      title: `Article ${i}`,
      published_at: hoursAgo(i * 0.1),
    }));
    vi.mocked(useSSE).mockReturnValue({ events });
    render(<NewsFeed />);
    expect(screen.getAllByText(/^Article \d+$/)).toHaveLength(20);
  });

  it("hides articles older than 23 hours", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [
        { symbol: "AAPL", uuid: "1", title: "Recent article", published_at: hoursAgo(22) },
        { symbol: "AAPL", uuid: "2", title: "Stale article", published_at: hoursAgo(24) },
      ],
    });
    render(<NewsFeed />);
    expect(screen.getByText(/Recent article/)).toBeInTheDocument();
    expect(screen.queryByText(/Stale article/)).not.toBeInTheDocument();
  });

  it("hides articles with no published_at, since their age can't be confirmed", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [{ symbol: "AAPL", uuid: "1", title: "Undated article" }],
    });
    render(<NewsFeed />);
    expect(screen.queryByText(/Undated article/)).not.toBeInTheDocument();
  });

  it("links the headline to the article url in a new tab", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [
        {
          symbol: "AAPL",
          uuid: "1",
          title: "Linked article",
          published_at: hoursAgo(1),
          url: "https://example.com/article",
        },
      ],
    });
    render(<NewsFeed />);
    const link = screen.getByRole("link", { name: /Linked article/ });
    expect(link).toHaveAttribute("href", "https://example.com/article");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders the headline as plain text when no url is present", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [{ symbol: "AAPL", uuid: "1", title: "Unlinked article", published_at: hoursAgo(1) }],
    });
    render(<NewsFeed />);
    expect(screen.getByText(/Unlinked article/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
