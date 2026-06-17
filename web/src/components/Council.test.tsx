import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CouncilEvent } from "../api/types";
import { Council } from "./Council";

const events: CouncilEvent[] = [
  {
    type: "panel_started",
    data: {
      ticker: "NVDA",
      models: ["anthropic/claude-opus-4.8", "openai/gpt-5.5", "google/gemini-3.1-pro", "x-ai/grok-4.3"]
    }
  },
  {
    type: "panel_model_result",
    data: {
      model_id: "anthropic/claude-opus-4.8",
      label: "Claude Opus 4.8",
      rating: "Buy",
      confidence: 0.84,
      thesis: "Demand durability supports upside.",
      dissent: false
    }
  },
  {
    type: "panel_model_result",
    data: {
      model_id: "openai/gpt-5.5",
      label: "GPT-5.5",
      rating: "Buy",
      confidence: 0.78,
      thesis: "Margins can keep compounding.",
      dissent: false
    }
  },
  {
    type: "panel_model_result",
    data: {
      model_id: "google/gemini-3.1-pro",
      label: "Gemini 3.1 Pro",
      rating: "Buy",
      confidence: 0.73,
      thesis: "The AI capex cycle still has breadth.",
      dissent: false
    }
  },
  {
    type: "panel_model_result",
    data: {
      model_id: "x-ai/grok-4.3",
      label: "Grok 4.3",
      rating: "Hold",
      confidence: 0.62,
      thesis: "Valuation already discounts a lot of perfection.",
      dissent: true
    }
  },
  {
    type: "judge_result",
    data: {
      consensus: ["AI demand remains the dominant driver."],
      contradictions: ["The panel split on valuation and timing."],
      blind_spots: ["Export controls require more evidence."],
      crowded_narrative_flag: {
        topic: "AI infrastructure",
        note: "Consensus leans on a heavily owned market narrative."
      }
    }
  },
  {
    type: "verdict",
    data: {
      ticker: "NVDA",
      rating: "Buy",
      conviction: 0.76,
      conviction_label: "High — with a timing caveat",
      scenarios: [
        { name: "Bull", probability: 0.3, ret_pct: 35 },
        { name: "Base", probability: 0.5, ret_pct: 12 },
        { name: "Bear", probability: 0.2, ret_pct: -18 }
      ],
      catalysts: ["Earnings"],
      risks: ["Multiple compression"]
    }
  }
];

describe("Council signature", () => {
  it("renders resolved panel cards, dissent, judge groups, and crowded narrative caution", () => {
    render(<Council events={events} />);

    expect(screen.getAllByTestId("panel-card")).toHaveLength(4);
    expect(screen.getAllByTestId("panel-card").filter((card) => card.dataset.resolved === "true")).toHaveLength(4);
    expect(screen.getByText("Hold")).toBeInTheDocument();
    expect(screen.getByText("dissent")).toBeInTheDocument();
    expect(screen.getByText("Consensus")).toBeInTheDocument();
    expect(screen.getByText("Contradictions")).toBeInTheDocument();
    expect(screen.getByText("Blind spots")).toBeInTheDocument();
    expect(screen.getByText("Consensus rests on a crowded narrative — confidence adjusted down.")).toBeInTheDocument();
  });

  it("shows a degraded completion state when a run ends before panel results arrive", () => {
    render(
      <Council
        events={[
          { type: "panel_started", data: { ticker: "NVDA", models: ["gemini-3.1-pro-preview"] } },
          {
            type: "done",
            data: {
              cost_usd: 0,
              degraded_reasons: ["Council skipped because COUNCIL_COST_CAP_USD is 0."]
            }
          }
        ]}
      />
    );

    expect(screen.getByText("Done with limits")).toBeInTheDocument();
    expect(screen.getByText("Council skipped because COUNCIL_COST_CAP_USD is 0.")).toBeInTheDocument();
    expect(screen.getByText("No panel results arrived before the run completed.")).toBeInTheDocument();
    expect(screen.queryByText("Deliberating")).not.toBeInTheDocument();
  });
});
