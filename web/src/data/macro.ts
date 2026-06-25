import type { MacroRegime, MacroTheme } from "../types";

export const macroRegime: MacroRegime = {
  call: "Cautiously Risk-On",
  score: 62,
  confidence: 71,
  rationale:
    "Liquidity conditions remain accommodative, but sticky services inflation and resilient payrolls push back the rate-cut window. AI capex cycle is the dominant micro driver while macro uncertainty is rising.",
  agent: "Macro Scanner",
  scannedAt: new Date(Date.now() - 1000 * 60 * 14).toISOString(),
};

export const macroThemes: MacroTheme[] = [
  {
    id: "rates",
    title: "Rates / Fed Policy",
    status: "neutral",
    confidence: 58,
    trend: "up",
    bullets: [
      "2Y Treasury yields +22 bps this week",
      "Market pricing 1.6 cuts in 2026 vs 2.4 last month",
      "Services inflation sticky in core PCE",
    ],
    agent: "Macro Scanner",
    scannedAt: new Date(Date.now() - 1000 * 60 * 14).toISOString(),
  },
  {
    id: "liquidity",
    title: "Global Liquidity",
    status: "risk_on",
    confidence: 71,
    trend: "up",
    bullets: [
      "G4 central bank balance sheets expanding modestly",
      "RRP drains continue to fund risk assets",
      "Dollar liquidity swaps remain benign",
    ],
    agent: "Macro Scanner",
    scannedAt: new Date(Date.now() - 1000 * 60 * 14).toISOString(),
  },
  {
    id: "usd",
    title: "USD Strength",
    status: "risk_off",
    confidence: 64,
    trend: "up",
    bullets: [
      "DXY near 2025 highs on rate differential",
      "EMFX stress contained but widening",
      "Exporters (TSM, AVGO) face modest headwind",
    ],
    agent: "Macro Scanner",
    scannedAt: new Date(Date.now() - 1000 * 60 * 14).toISOString(),
  },
  {
    id: "energy",
    title: "Energy / Power",
    status: "risk_on",
    confidence: 75,
    trend: "up",
    bullets: [
      "Datacenter power demand revisions accelerate",
      "Grid-related names (GEV, ETN, VRT) outperforming",
      "Oil supply discipline keeps Brent range-bound",
    ],
    agent: "Macro Scanner",
    scannedAt: new Date(Date.now() - 1000 * 60 * 14).toISOString(),
  },
  {
    id: "ai-capex",
    title: "AI Capex Cycle",
    status: "risk_on",
    confidence: 82,
    trend: "up",
    bullets: [
      "Hyperscaler spend +40% y/y guidance",
      "Custom silicon demand rising (AVGO, MRVL)",
      "Cooling/power constraints favor incumbents",
    ],
    agent: "Macro Scanner",
    scannedAt: new Date(Date.now() - 1000 * 60 * 14).toISOString(),
  },
];
