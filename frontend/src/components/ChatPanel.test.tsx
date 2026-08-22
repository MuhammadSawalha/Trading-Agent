// frontend/src/components/ChatPanel.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ChatPanel } from "./ChatPanel";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends a question and displays the answer", async () => {
    vi.mocked(apiClient.sendChatMessage).mockResolvedValue({ answer: "AAPL looks bullish." });
    render(<ChatPanel />);
    fireEvent.change(screen.getByPlaceholderText(/ask about your watchlist/i), { target: { value: "How does AAPL look?" } });
    fireEvent.click(screen.getByText(/send/i));
    await waitFor(() => expect(screen.getByText(/AAPL looks bullish/)).toBeInTheDocument());
    expect(apiClient.sendChatMessage).toHaveBeenCalledWith("How does AAPL look?", []);
  });

  it("shows an error message when sending fails, without losing the user's question", async () => {
    vi.mocked(apiClient.sendChatMessage).mockRejectedValue(new Error("network error"));
    render(<ChatPanel />);
    fireEvent.change(screen.getByPlaceholderText(/ask about your watchlist/i), { target: { value: "How does AAPL look?" } });
    fireEvent.click(screen.getByText(/send/i));
    await waitFor(() => expect(screen.getByText(/something went wrong/i)).toBeInTheDocument());
    expect(screen.getByText("How does AAPL look?")).toBeInTheDocument();
  });

  it("renders the assistant's markdown as real structured elements, not raw '**'/'#'/'|' text", async () => {
    vi.mocked(apiClient.sendChatMessage).mockResolvedValue({
      answer:
        "# MSFT vs GOOG\n\n**Edge: MSFT** on execution.\n\n" +
        "| Metric | MSFT | GOOG |\n|---|---|---|\n| P/E | 22.9 | 32.8 |\n",
    });
    render(<ChatPanel />);
    fireEvent.change(screen.getByPlaceholderText(/ask about your watchlist/i), { target: { value: "compare" } });
    fireEvent.click(screen.getByText(/send/i));

    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: "MSFT vs GOOG" })).toBeInTheDocument());
    // Bold text becomes a real <strong>, not a literal "**Edge: MSFT**" substring.
    const bold = screen.getByText("Edge: MSFT");
    expect(bold.tagName).toBe("STRONG");
    // The markdown table becomes a real <table> with cell text, not a literal "| P/E | ... |" line.
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Metric" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "22.9" })).toBeInTheDocument();
    // None of the raw markdown syntax should leak through as literal visible text.
    expect(screen.queryByText(/\*\*Edge/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^\| Metric/)).not.toBeInTheDocument();
  });

  it("shows topic chips before any message is sent", () => {
    render(<ChatPanel />);
    expect(screen.getByText("Technicals")).toBeInTheDocument();
    expect(screen.getByText("Comparisons")).toBeInTheDocument();
    expect(screen.getByText("Across my watchlist")).toBeInTheDocument();
  });

  it("walks topic -> question -> stock and sends the composed question", async () => {
    vi.mocked(apiClient.sendChatMessage).mockResolvedValue({ answer: "1.6x average volume." });
    render(<ChatPanel symbols={["AAPL", "MSFT"]} />);

    fireEvent.click(screen.getByText("Technicals"));
    fireEvent.click(screen.getByText("Unusual volume"));
    fireEvent.click(screen.getByText("AAPL"));

    expect(apiClient.sendChatMessage).toHaveBeenCalledWith("Is there unusual volume on AAPL?", ["AAPL"]);
    await waitFor(() => expect(screen.getByText(/1.6x average volume/)).toBeInTheDocument());
  });

  it("requires two stocks for a comparison question before sending", async () => {
    vi.mocked(apiClient.sendChatMessage).mockResolvedValue({ answer: "AAPL edges out MSFT." });
    render(<ChatPanel symbols={["AAPL", "MSFT"]} />);

    fireEvent.click(screen.getByText("Comparisons"));
    fireEvent.click(screen.getByText("Full comparison"));
    fireEvent.click(screen.getByText("AAPL"));
    expect(apiClient.sendChatMessage).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("MSFT"));
    expect(apiClient.sendChatMessage).toHaveBeenCalledWith(
      "Give me a full comparison between AAPL and MSFT.",
      ["AAPL", "MSFT"]
    );
    await waitFor(() => expect(screen.getByText(/edges out/)).toBeInTheDocument());
  });

  it("sends a portfolio-wide question against the full watchlist without a stock-picking step", async () => {
    vi.mocked(apiClient.sendChatMessage).mockResolvedValue({ answer: "AAPL has the strongest bull case." });
    render(<ChatPanel symbols={["AAPL", "MSFT", "GOOG"]} />);

    fireEvent.click(screen.getByText("Across my watchlist"));
    fireEvent.click(screen.getByText("Most bullish setup"));

    expect(apiClient.sendChatMessage).toHaveBeenCalledWith(
      "Which stock in my watchlist has the strongest bull case right now?",
      ["AAPL", "MSFT", "GOOG"]
    );
    await waitFor(() => expect(screen.getByText(/strongest bull case/)).toBeInTheDocument());
  });

  it("returns to the topic chips after an answer comes back", async () => {
    vi.mocked(apiClient.sendChatMessage).mockResolvedValue({ answer: "Bullish, moderate confidence." });
    render(<ChatPanel symbols={["AAPL"]} />);

    fireEvent.click(screen.getByText("Composite score / overview"));
    fireEvent.click(screen.getByText("Current composite score"));
    fireEvent.click(screen.getByText("AAPL"));

    await waitFor(() => expect(screen.getByText(/Bullish, moderate confidence/)).toBeInTheDocument());
    expect(screen.getByText("Ask about something else")).toBeInTheDocument();
    expect(screen.getByText("Technicals")).toBeInTheDocument();
  });
});
