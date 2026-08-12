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
