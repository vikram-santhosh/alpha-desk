import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { IdeaScoutResult } from "../api/types";
import { IdeaScout } from "./IdeaScout";

const result: IdeaScoutResult = {
  as_of: "2026-06-17",
  universe: "US-listed liquid equities and ADRs",
  scout_mode: "top_buys",
  cost_usd: 0,
  degraded_reasons: [],
  disclaimer: "Research candidates only.",
  audit: {
    mode: "top_buys",
    source_counts: { "existing universe": 3 },
    raw_candidates: 28,
    unique_candidates: 20,
    capped_candidates: 20,
    existing_universe_count: 3,
    excluded_existing: [],
    tracked_ticker_checks: {
      AMZN: { included: true, source: "existing_portfolio", mode: "top_buys" },
      META: { included: true, source: "existing_watchlist", mode: "top_buys" },
      AVGO: { included: true, source: "existing_watchlist", mode: "top_buys" }
    }
  },
  data_source_checks: [
    {
      source: "OpenRouter scout",
      status: "validated",
      detail: "Scout model returned structured ideas.",
      checked_at: "2026-06-17"
    },
    {
      source: "Reddit moonshot",
      status: "configured",
      detail: "Configured but not fetched during this run.",
      checked_at: "2026-06-17"
    },
    {
      source: "Kalshi prediction markets",
      status: "unavailable",
      detail: "Kalshi was not queried.",
      checked_at: "2026-06-17"
    }
  ],
  ideas: [
    {
      rank: 1,
      ticker: "NVDA",
      company: "NVIDIA",
      theme: "AI accelerators",
      score: 0.91,
      horizon: "6-18 months",
      thesis: "AI infrastructure demand still compounds.",
      catalysts: ["Earnings"],
      risks: ["Valuation"],
      source: "Mock"
    },
    {
      rank: 2,
      ticker: "MSFT",
      company: "Microsoft",
      theme: "AI platform",
      score: 0.88,
      horizon: "6-18 months",
      thesis: "Azure AI demand supports durable compounding.",
      catalysts: ["Cloud growth"],
      risks: ["Macro"],
      source: "Mock"
    }
  ]
};

describe("IdeaScout", () => {
  it("stays hidden before a scout run", () => {
    const { container } = render(<IdeaScout status="idle" onRunIdea={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders ranked ideas and launches council from a card", () => {
    const onRunIdea = vi.fn();
    render(<IdeaScout result={result} status="complete" onRunIdea={onRunIdea} />);

    expect(screen.getByRole("heading", { name: "Alpha Scout top buys" })).toBeInTheDocument();
    expect(screen.getAllByTestId("idea-card")).toHaveLength(2);
    expect(screen.getAllByTestId("source-check")).toHaveLength(3);
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.getByText("OpenRouter scout")).toBeInTheDocument();
    expect(screen.getByText("Top buys")).toBeInTheDocument();
    expect(screen.getByText("META included")).toBeInTheDocument();
    expect(screen.getByText("Validated")).toBeInTheDocument();
    expect(screen.getByText("Configured")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Run council" })[0]);

    expect(onRunIdea).toHaveBeenCalledWith(result.ideas[0]);
  });

  it("renders an error state", () => {
    render(<IdeaScout status="error" error="Idea scout failed." onRunIdea={vi.fn()} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Idea scout failed.");
  });
});
