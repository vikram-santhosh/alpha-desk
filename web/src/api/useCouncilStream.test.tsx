import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCouncilStream } from "./useCouncilStream";

type Listener = (event: Event) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  closed = false;
  private readonly listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data?: unknown) {
    const event =
      data === undefined
        ? new Event(type)
        : new MessageEvent(type, { data: JSON.stringify(data) });
    (this.listeners.get(type) ?? []).forEach((listener) => listener(event));
  }
}

const verdict = {
  ticker: "NVDA",
  rating: "Buy" as const,
  conviction: 0.74,
  conviction_label: "High with valuation risk",
  scenarios: [
    { name: "Bull" as const, probability: 0.3, ret_pct: 35 },
    { name: "Base" as const, probability: 0.5, ret_pct: 12 },
    { name: "Bear" as const, probability: 0.2, ret_pct: -18 }
  ],
  catalysts: ["Earnings"],
  risks: ["Valuation"]
};

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useCouncilStream", () => {
  it("streams the happy path into typed council state", () => {
    const { result } = renderHook(() => useCouncilStream());

    act(() => {
      result.current.runCouncil({ ticker: "NVDA", models: ["anthropic/claude-opus-4.8"] });
    });

    const source = FakeEventSource.instances[0];
    expect(source.url).toContain("ticker=NVDA");
    expect(source.url).toContain("models=anthropic%2Fclaude-opus-4.8");

    act(() => {
      source.emit("panel_started", { ticker: "NVDA", models: ["anthropic/claude-opus-4.8"] });
      source.emit("panel_model_result", {
        model_id: "anthropic/claude-opus-4.8",
        label: "Claude Opus 4.8",
        rating: "Buy",
        confidence: 0.82,
        thesis: "Durable AI demand.",
        dissent: false
      });
      source.emit("judge_result", {
        consensus: ["Demand"],
        contradictions: [],
        blind_spots: []
      });
      source.emit("verdict", verdict);
      source.emit("done", { cost_usd: 0.42, degraded_reasons: [], council_mode: "openrouter_live" });
    });

    expect(result.current.status).toBe("complete");
    expect(result.current.verdict?.ticker).toBe("NVDA");
    expect(result.current.done?.cost_usd).toBe(0.42);
    expect(source.closed).toBe(true);
  });

  it("keeps the last completed run visible when a later stream errors", () => {
    const { result } = renderHook(() => useCouncilStream());

    act(() => {
      result.current.runCouncil({ ticker: "NVDA", models: ["anthropic/claude-opus-4.8"] });
    });
    act(() => {
      const firstSource = FakeEventSource.instances[0];
      firstSource.emit("panel_started", { ticker: "NVDA", models: ["anthropic/claude-opus-4.8"] });
      firstSource.emit("verdict", verdict);
      firstSource.emit("done", { cost_usd: 0.42, degraded_reasons: [], council_mode: "openrouter_live" });
    });

    act(() => {
      result.current.runCouncil({ ticker: "AMZN", models: ["x-ai/grok-4.3"] });
    });
    act(() => {
      const secondSource = FakeEventSource.instances[1];
      secondSource.emit("panel_started", { ticker: "AMZN", models: ["x-ai/grok-4.3"] });
      secondSource.emit("error", { message: "Council call failed. Showing the last completed run — retry?" });
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("Council call failed. Showing the last completed run — retry?");
    expect(result.current.verdict?.ticker).toBe("NVDA");

    act(() => {
      result.current.retry();
    });

    expect(FakeEventSource.instances.at(-1)?.url).toContain("ticker=AMZN");
  });
});
