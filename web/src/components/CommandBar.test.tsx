import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ModelOption } from "../api/types";
import { CommandBar } from "./CommandBar";

const roster: ModelOption[] = [
  { model_id: "google/gemini-3.5-flash", label: "Gemini 3.5 Flash", provider: "Google", enabled: true },
  { model_id: "moonshotai/kimi-k2.7-code", label: "Kimi K2.7 Code", provider: "Moonshot AI", enabled: true }
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
      models: ["google/gemini-3.5-flash", "moonshotai/kimi-k2.7-code"]
    });
  });

  it("removes disabled chips from the run request", () => {
    const onRun = vi.fn();
    render(<CommandBar roster={roster} status="No run yet" onRun={onRun} />);

    fireEvent.click(screen.getByRole("button", { name: /Kimi K2.7 Code/ }));
    fireEvent.change(screen.getByLabelText("Ticker or idea"), { target: { value: "AMZN" } });
    fireEvent.click(screen.getByRole("button", { name: "Run council" }));

    expect(onRun).toHaveBeenCalledWith({
      ticker: "AMZN",
      models: ["google/gemini-3.5-flash"]
    });
  });

  it("disables Run council when the last model is toggled off", () => {
    const onRun = vi.fn();
    render(<CommandBar roster={[roster[0]]} status="No run yet" onRun={onRun} />);

    fireEvent.change(screen.getByLabelText("Ticker or idea"), { target: { value: "MSFT" } });
    fireEvent.click(screen.getByRole("button", { name: /Gemini 3.5 Flash/ }));

    expect(screen.getByRole("button", { name: "Run council" })).toBeDisabled();
  });

  it("dispatches the idea scout button and disables it while loading", () => {
    const onScout = vi.fn();
    const { rerender } = render(
      <CommandBar
        roster={roster}
        status="No run yet"
        onRun={vi.fn()}
        onScout={onScout}
        scoutStatus="loading"
      />
    );

    expect(screen.getByRole("button", { name: "Scouting..." })).toBeDisabled();

    rerender(<CommandBar roster={roster} status="No run yet" onRun={vi.fn()} onScout={onScout} />);
    fireEvent.click(screen.getByRole("button", { name: "Run Alpha Scout discovery" }));

    expect(onScout).toHaveBeenCalledTimes(1);
  });
});
