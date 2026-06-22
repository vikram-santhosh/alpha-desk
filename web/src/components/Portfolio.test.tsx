import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PortfolioSnapshot } from "../api/types";
import { PortfolioPanel } from "./Portfolio";

const snapshot: PortfolioSnapshot = {
  positions: [
    { ticker: "NVDA", weight_pct: 70, rating: "Buy" },
    { ticker: "AMZN", weight_pct: 20, rating: "Overweight" },
    { ticker: "MSFT", weight_pct: 10, rating: "Hold" }
  ],
  top_holding_pct: 70,
  top3_pct: 100,
  concentration_flag: true
};

describe("PortfolioPanel", () => {
  it("renders allocation segments and flags concentrated portfolios", () => {
    render(<PortfolioPanel snapshot={snapshot} />);

    expect(screen.getByRole("heading", { name: "Allocation map" })).toBeInTheDocument();
    expect(screen.getByText(/Concentration flag/)).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();

    const segments = screen.getAllByTestId("allocation-segment");
    const totalWeight = segments.reduce(
      (total, segment) => total + Number(segment.getAttribute("data-weight")),
      0
    );

    expect(segments).toHaveLength(3);
    expect(totalWeight).toBe(100);
  });

  it("shows the requested empty state without holdings", () => {
    render(<PortfolioPanel />);

    expect(screen.getByRole("heading", { name: "No portfolio loaded" })).toBeInTheDocument();
  });
});
