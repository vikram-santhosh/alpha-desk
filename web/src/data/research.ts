import type { ResearchReport } from "../types";

export const researchReports: ResearchReport[] = [
  {
    id: "rpt-1",
    title: "TSM: CoWoS capacity expansion and China risk repricing",
    tickers: ["TSM"],
    agent: "Deep Research Analyst",
    tier: "deep",
    freshness: "2h ago",
    summary:
      "Leading-edge capacity remains sold out through 2026. The key debate is how much China-revenue risk is already priced in and whether Arizona ramp de-risks geopolitical concentration.",
    verdict: "Hold / accumulate on weakness",
    confidence: 72,
    sections: [
      { heading: "Thesis", content: "Monopoly-like position in advanced packaging underpins AI chip supply chain." },
      { heading: "Bull case", content: "CoWoS capacity doubles; Apple/AMD/NVDA demand inelastic." },
      { heading: "Bear case", content: "China invasion tail risk; Arizona costs higher than expected." },
      { heading: "Catalysts", content: "Q2 guidance, export-control updates, Arizona milestone." },
      { heading: "Risks", content: "Geopolitics, cyclical memory spend, margin compression." },
      { heading: "Verdict", content: "Hold; add if valuation compresses below 18x forward." },
    ],
  },
  {
    id: "rpt-2",
    title: "Power/grid theme: GEV vs ETN vs VRT",
    tickers: ["GEV", "ETN", "VRT"],
    agent: "Causal Reasoner",
    tier: "deep",
    freshness: "5h ago",
    summary:
      "Data-center power demand is the second-order play from AI compute. GEV has the most torque to generation, ETN to distribution, VRT to thermal management.",
    verdict: "Overweight power/grid basket",
    confidence: 68,
    sections: [
      { heading: "Thesis", content: "AI racks are power-constrained before they are compute-constrained." },
      { heading: "Bull case", content: "Multi-year utility capex cycle; backlog visibility >2 years." },
      { heading: "Bear case", content: "Valuation stretched; interest-rate sensitivity." },
      { heading: "Catalysts", content: "Utility guidance, datacenter project announcements." },
      { heading: "Risks", content: "Project delays, rate volatility, execution." },
      { heading: "Verdict", content: "Equal-weight basket; trim if forward P/E >35x." },
    ],
  },
  {
    id: "rpt-3",
    title: "Quick scan: CRWD post-outage recovery",
    tickers: ["CRWD"],
    agent: "News Desk",
    tier: "quick",
    freshness: "1d ago",
    summary:
      "Channel checks suggest Falcon platform retention remains high. The outage is a near-term headwind but competitive positioning is intact.",
    verdict: "Watch",
    confidence: 55,
    sections: [
      { heading: "Signal", content: "Customer churn lower than feared; MSP attach stable." },
      { heading: "Verdict", content: "Watch for a better entry near $330." },
    ],
  },
];
