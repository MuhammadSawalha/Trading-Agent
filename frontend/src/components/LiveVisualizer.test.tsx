import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { LiveVisualizer } from "./LiveVisualizer";
import { useSSE } from "../hooks/useSSE";

vi.mock("../hooks/useSSE");

describe("LiveVisualizer", () => {
  it("shows a node as running after a started event and finished after a finished event", () => {
    vi.mocked(useSSE).mockReturnValue({
      events: [
        { agent: "Fundamentals", status: "started", timestamp: "t1", reason: "scheduled_refresh" },
        { agent: "Fundamentals", status: "finished", timestamp: "t2", reason: "scheduled_refresh" },
        { agent: "Technical", status: "started", timestamp: "t3", reason: "scheduled_refresh" },
      ],
    });
    render(<LiveVisualizer symbol="AAPL" />);
    expect(screen.getByTestId("viz-node-Fundamentals").textContent).toContain("finished");
    expect(screen.getByTestId("viz-node-Technical").textContent).toContain("running");
    expect(screen.getByTestId("viz-node-Risk").textContent).toContain("idle");
  });
});
