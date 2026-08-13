// frontend/src/components/ChatPanel.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";
import { apiClient } from "../api/client";

vi.mock("../api/client");

describe("ChatPanel", () => {
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
});
