import type { PortfolioSummary, SleevePosition, SparklinePoint } from "../types";

export const sleeve: Omit<SleevePosition, "price" | "changePct" | "value" | "shares" | "sparkline" | "thesis" | "thesisStatus" | "breach">[] = [
  { ticker: "TSM", name: "Taiwan Semiconductor", weight: 0.15, theme: "AI compute" },
  { ticker: "UBER", name: "Uber Technologies", weight: 0.15, theme: "Mobility/ads" },
  { ticker: "NVDA", name: "NVIDIA", weight: 0.13, theme: "AI compute" },
  { ticker: "CRWD", name: "CrowdStrike", weight: 0.11, theme: "Cybersecurity" },
  { ticker: "AVGO", name: "Broadcom", weight: 0.10, theme: "AI networking" },
  { ticker: "ETN", name: "Eaton", weight: 0.08, theme: "Electrification" },
  { ticker: "GEV", name: "GE Vernova", weight: 0.07, theme: "Power/grid" },
  { ticker: "VRT", name: "Vertiv", weight: 0.06, theme: "Datacenter cooling" },
  { ticker: "SGOV", name: "0–3mo T-Bill ETF", weight: 0.15, theme: "Cash" },
];

const basePrices: Record<string, number> = {
  TSM: 186,
  UBER: 78,
  NVDA: 124,
  CRWD: 373,
  AVGO: 196,
  ETN: 298,
  GEV: 293,
  VRT: 87,
  SGOV: 100,
};

const theses: Record<string, string> = {
  TSM: "Leading-edge foundry monopoly benefits from AI compute capex.",
  UBER: "Mobility network plus advertising flywheel rerating higher.",
  NVDA: "GPU dominance extends to inference as workloads scale.",
  CRWD: "Platform consolidation winner in endpoint security.",
  AVGO: "Custom silicon + networking exposure to AI clusters.",
  ETN: "Electrification backlog driven by grid modernization.",
  GEV: "Power-generation beneficiary of data-center energy demand.",
  VRT: "Thermal management critical to dense AI racks.",
  SGOV: "Liquidity buffer and dry powder for drawdowns.",
};

function generateSparkline(seed: number, trend = 0): SparklinePoint[] {
  const points: SparklinePoint[] = [];
  let value = seed;
  for (let i = 0; i < 30; i++) {
    value = value * (1 + (Math.random() - 0.5) * 0.025 + trend * 0.002);
    points.push({ value });
  }
  return points;
}

const TOTAL_PORTFOLIO_VALUE = 1_240_000;

export const positions: SleevePosition[] = sleeve.map((s) => {
  const base = basePrices[s.ticker];
  const changePct = s.ticker === "SGOV" ? 0.01 : (Math.random() - 0.4) * 6;
  const price = base * (1 + changePct / 100);
  const value = TOTAL_PORTFOLIO_VALUE * s.weight;
  const shares = Math.round(value / price);
  const breach = s.ticker === "NVDA" ? "warning" : null;
  const statusPool: SleevePosition["thesisStatus"][] = ["strong", "intact", "intact", "under_review", "degraded"];
  const thesisStatus = statusPool[Math.floor(Math.random() * statusPool.length)];
  return {
    ...s,
    price,
    changePct,
    value,
    shares,
    sparkline: generateSparkline(base, changePct > 0 ? 0.3 : -0.3),
    thesis: theses[s.ticker],
    thesisStatus,
    breach,
  };
});

export const portfolioSummary: PortfolioSummary = {
  totalValue: TOTAL_PORTFOLIO_VALUE,
  dayPnl: positions.reduce((sum, p) => sum + p.value * (p.changePct / 100), 0),
  dayPnlPct: positions.reduce((sum, p) => sum + p.weight * p.changePct, 0),
  cash: positions.find((p) => p.ticker === "SGOV")?.value ?? 186_000,
  activeBreachCount: positions.filter((p) => p.breach).length,
  activeSignalCount: 12,
  asOf: new Date().toISOString(),
};
