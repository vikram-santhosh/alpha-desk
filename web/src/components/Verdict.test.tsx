import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Verdict } from "../api/types";
import { VerdictPanel } from "./Verdict";

const verdict: Verdict = {
  ticker: "NVDA",
  rating: "Buy",
  conviction: 0.74,
  conviction_label: "High with valuation risk",
  scenarios: [
    { name: "Bull", probability: 0.3, ret_pct: 35 },
    { name: "Base", probability: 0.5, ret_pct: 12 },
    { name: "Bear", probability: 0.2, ret_pct: -18 }
  ],
  catalysts: ["Blackwell supply expansion", "Enterprise AI capex"],
  risks: ["Multiple compression"]
};

describe("VerdictPanel", () => {
  it("renders the verdict gauge, scenarios, catalysts, and risks from payload data", () => {
    render(<VerdictPanel verdict={verdict} />);

    expect(screen.getByRole("heading", { name: "NVDA synthesis" })).toBeInTheDocument();
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Conviction" })).toHaveAttribute("aria-valuenow", "74");
    expect(screen.getByTestId("conviction-arc")).toHaveAttribute("stroke-dasharray", "74 100");
    expect(screen.getAllByTestId("scenario-bar")).toHaveLength(3);
    expect(screen.getByText("30% · +35.0%")).toBeInTheDocument();
    expect(screen.getByText("50% · +12.0%")).toBeInTheDocument();
    expect(screen.getByText("20% · -18.0%")).toBeInTheDocument();
    expect(screen.getByText("Blackwell supply expansion")).toBeInTheDocument();
    expect(screen.getByText("Multiple compression")).toBeInTheDocument();
  });
});
