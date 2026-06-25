import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      headers: { "Content-Type": "application/json" },
      status,
    })
  );
}

describe("AlphaDesk cockpit", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/council/models")) {
          return jsonResponse([
            { model_id: "z-ai/glm-5.2", label: "GLM 5.2", provider: "z-ai", enabled: true },
          ]);
        }
        if (url.includes("/api/macro")) {
          return jsonResponse({
            regime: {
              call: "risk-on",
              score: 72,
              confidence: 81,
              rationale: "Backend smoke-test macro regime.",
              agent: "macro",
              scannedAt: "2026-06-22T20:30:00",
              source: "backend",
            },
            themes: [],
            degraded_reasons: [],
          });
        }
        if (url.includes("/api/portfolio")) {
          return jsonResponse({
            positions: [{ ticker: "NVDA", weight_pct: 12.5 }],
            top_holding_pct: 12.5,
            top3_pct: 12.5,
            concentration_flag: false,
          });
        }
        return jsonResponse({}, 404);
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the themed backend cockpit shell", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Backend Cockpit" })).toBeTruthy();
    expect(screen.getAllByText("Alpha Scout").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Model Council").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Macro Regime").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Portfolio").length).toBeGreaterThan(0);
  });
});
