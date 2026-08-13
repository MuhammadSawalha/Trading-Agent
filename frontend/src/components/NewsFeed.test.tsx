import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { NewsFeed } from "./NewsFeed";
import { useSSE } from "../hooks/useSSE";

vi.mock("../hooks/useSSE");

describe("NewsFeed", () => {
  it("renders articles newest-first", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [
        { symbol: "AAPL", uuid: "1", title: "Older article", published_at: "2026-01-01T00:00:00Z" },
        { symbol: "NVDA", uuid: "2", title: "Newer article", published_at: "2026-01-02T00:00:00Z" },
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
        { symbol: "AAPL", uuid: "1", title: "Original article", published_at: "2026-01-01T00:00:00Z" },
        { symbol: "AAPL", uuid: "1", title: "Original article", published_at: "2026-01-01T00:00:00Z" },
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
        { symbol: "MSFT", uuid: "1", title: "Azure article", published_at: "2026-01-01T00:00:00Z" },
        { symbol: "GOOG", uuid: "2", title: "Google article", published_at: "2026-01-01T00:00:00Z" },
      ],
    });
    render(<NewsFeed symbols={["GOOG"]} />);
    expect(screen.queryByText(/Azure article/)).not.toBeInTheDocument();
    expect(screen.getByText(/Google article/)).toBeInTheDocument();
  });

  it("shows every article when no symbols filter is provided", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [
        { symbol: "MSFT", uuid: "1", title: "Azure article", published_at: "2026-01-01T00:00:00Z" },
      ],
    });
    render(<NewsFeed />);
    expect(screen.getByText(/Azure article/)).toBeInTheDocument();
  });

  it("caps the rendered list at 20 articles", () => {
    const events = Array.from({ length: 25 }, (_, i) => ({
      symbol: "AAPL",
      uuid: String(i),
      title: `Article ${i}`,
      published_at: `2026-01-01T00:00:${String(i).padStart(2, "0")}Z`,
    }));
    vi.mocked(useSSE).mockReturnValue({ events });
    render(<NewsFeed />);
    expect(screen.getAllByText(/^Article \d+$/)).toHaveLength(20);
  });
});
