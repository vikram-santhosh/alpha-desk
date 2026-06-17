import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ModelOption } from "../api/types";
import { CommandBar } from "./CommandBar";

const roster: ModelOption[] = [
  { model_id: "anthropic/claude-opus-4.8", label: "Claude Opus 4.8", provider: "Anthropic", enabled: true },
  { model_id: "google/gemini-3.1-pro-preview", label: "Gemini 3.1 Pro", provider: "Google", enabled: true }
];

describe("CommandBar", () => {
  it("dispatches a run with normalized ticker and enabled model ids on Enter", () => {
    const onRun = vi.fn();
    render(<CommandBar roster={roster} status="No run yet" onRun={onRun} />);

    const input = screen.getByLabelText("Ticker or idea");
    fireEvent.change(input, { target: { value: " nvda " } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onRun).toHaveBeenCalledWith({
      ticker: "NVDA",
      models: ["anthropic/claude-opus-4.8", "google/gemini-3.1-pro-preview"]
    });
  });

  it("removes disabled chips from the run request", () => {
    const onRun = vi.fn();
    render(<CommandBar roster={roster} status="No run yet" onRun={onRun} />);

    fireEvent.click(screen.getByRole("button", { name: /Gemini 3.1 Pro/ }));
    fireEvent.change(screen.getByLabelText("Ticker or idea"), { target: { value: "AMZN" } });
    fireEvent.click(screen.getByRole("button", { name: "Run council" }));

    expect(onRun).toHaveBeenCalledWith({
      ticker: "AMZN",
      models: ["anthropic/claude-opus-4.8"]
    });
  });

  it("disables Run council when the last model is toggled off", () => {
    const onRun = vi.fn();
    render(<CommandBar roster={[roster[0]]} status="No run yet" onRun={onRun} />);

    fireEvent.change(screen.getByLabelText("Ticker or idea"), { target: { value: "MSFT" } });
    fireEvent.click(screen.getByRole("button", { name: /Claude Opus 4.8/ }));

    expect(screen.getByRole("button", { name: "Run council" })).toBeDisabled();
  });
});
