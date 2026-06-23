import type { Moonshot } from "../types";

export const moonshots: Moonshot[] = [
  {
    id: "ms-1",
    ticker: "COOL",
    name: "AI Cooling Infrastructure",
    sector: "Technology",
    thesis:
      "Data center power density is outpacing thermal budgets. Liquid cooling and immersion players are the picks-and-shovels behind every new GPU cluster.",
    conviction: 62,
    asymmetry: { downside: 30, upside: 180 },
    whyNow: "Blackwell rack TDP crosses 100kW; air cooling hits physical limits.",
  },
  {
    id: "ms-2",
    ticker: "URA",
    name: "Uranium Miners",
    sector: "Energy",
    thesis:
      "Nuclear renaissance plus supply deficit. Small modular reactor announcements create a step-change in demand visibility.",
    conviction: 55,
    asymmetry: { downside: 25, upside: 140 },
    whyNow: "US utility contracting cycle is accelerating; Kazakhs signal slower supply growth.",
  },
  {
    id: "ms-3",
    ticker: "LMT",
    name: "Defense Primes",
    sector: "Defense",
    thesis:
      "Geopolitical reordering and allied defense-spending commitments underpin a multi-year budget up-cycle.",
    conviction: 58,
    asymmetry: { downside: 15, upside: 70 },
    whyNow: "European rearmament + Indo-Pacific deterrence drive procurement pipelines.",
  },
  {
    id: "ms-4",
    ticker: "GOLD",
    name: "Gold Miners",
    sector: "Commodities",
    thesis:
      "Real-rate peak + central-bank buying + fiscal-debasement hedging. Miners offer torque to a structurally higher gold price.",
    conviction: 51,
    asymmetry: { downside: 20, upside: 95 },
    whyNow: "Gold breaks $3,000; miners still trade below replacement cost.",
  },
];
