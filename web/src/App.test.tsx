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
        if (url.includes("/api/brief/runs/latest")) {
          return jsonResponse({
            run_id: 42,
            saved_at: "2026-06-22T20:30:00",
            run_type: "morning_full",
            formatted: "<b>AlphaDesk Daily Brief</b>\nHold current exposure.",
            sections: {},
            stats: { total_time_s: 12.3, run_cost: 0.12, holdings_count: 5 },
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

  it("renders the daily brief shell", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Daily Brief" })).toBeTruthy();
    expect(await screen.findByText(/AlphaDesk Daily Brief/)).toBeTruthy();
    expect(screen.getAllByText("Alpha Scout").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Portfolio").length).toBeGreaterThan(0);
  });
});
