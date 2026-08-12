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
});
