import type { TopBuysResult } from "@/types";

export const topBuysMock: TopBuysResult = {
  snapshot_id: "MOCK_20260623_070000_abc123",
  weights_version: "v1-config_mock",
  source: "mock",
  diagnostics: {
    elapsed_s: 0.007,
    signals_collected: 12,
    sensors_ok: ["earnings", "reddit"],
    sensors_failed: [],
    tickers_scored: 9,
  },
  top: [
    {
      ticker: "NVDA",
      score: 7.33,
      platforms_reporting: ["earnings", "reddit"],
      platforms_failed: [],
      breakdown: [
        { sensor: "earnings", direction: "BULL", strength: 0.9,  confidence: 0.9,  weight: 1.8, contribution:  1.458, evidence: "Strong guidance + upside EPS surprise" },
        { sensor: "reddit",   direction: "BULL", strength: 0.8,  confidence: 0.7,  weight: 0.8, contribution:  0.448, evidence: "25 mentions, avg_sentiment=+1.60" },
      ],
    },
    {
      ticker: "AMZN",
      score: 5.04,
      platforms_reporting: ["earnings", "reddit"],
      platforms_failed: [],
      breakdown: [
        { sensor: "earnings", direction: "BULL", strength: 0.7,  confidence: 0.85, weight: 1.8, contribution:  1.071, evidence: "AWS re-acceleration, raised guide" },
        { sensor: "reddit",   direction: "BULL", strength: 0.5,  confidence: 0.6,  weight: 0.8, contribution:  0.240, evidence: "12 mentions, avg_sentiment=+1.00" },
      ],
    },
    {
      ticker: "VRT",
      score: 3.63,
      platforms_reporting: ["earnings"],
      platforms_failed: [],
      breakdown: [
        { sensor: "earnings", direction: "BULL", strength: 0.7,  confidence: 0.75, weight: 1.8, contribution:  0.945, evidence: "Power/cooling demand, raised guide" },
      ],
    },
    {
      ticker: "MSFT",
      score: 3.60,
      platforms_reporting: ["earnings"],
      platforms_failed: [],
      breakdown: [
        { sensor: "earnings", direction: "BULL", strength: 0.65, confidence: 0.8,  weight: 1.8, contribution:  0.936, evidence: "Azure +33% YoY, Copilot attach rate rising" },
      ],
    },
    {
      ticker: "GOOG",
      score: 3.32,
      platforms_reporting: ["earnings", "reddit"],
      platforms_failed: [],
      breakdown: [
        { sensor: "earnings", direction: "BULL", strength: 0.6,  confidence: 0.8,  weight: 1.8, contribution:  0.864, evidence: "Cloud margin inflection" },
        { sensor: "reddit",   direction: "NEUTRAL", strength: 0.2, confidence: 0.5, weight: 0.8, contribution: 0.000, evidence: "4 mentions, avg_sentiment=+0.10" },
      ],
    },
    {
      ticker: "NFLX",
      score: 1.20,
      platforms_reporting: ["reddit"],
      platforms_failed: [],
      breakdown: [
        { sensor: "reddit", direction: "BULL", strength: 0.6,  confidence: 0.65, weight: 0.8, contribution: 0.312, evidence: "15 mentions, avg_sentiment=+1.20" },
      ],
    },
    {
      ticker: "META",
      score: 0.68,
      platforms_reporting: ["reddit"],
      platforms_failed: [],
      breakdown: [
        { sensor: "reddit", direction: "BULL", strength: 0.4,  confidence: 0.55, weight: 0.8, contribution: 0.176, evidence: "8 mentions, avg_sentiment=+0.80" },
      ],
    },
    {
      ticker: "AVGO",
      score: 0.00,
      platforms_reporting: ["earnings"],
      platforms_failed: [],
      breakdown: [
        { sensor: "earnings", direction: "NEUTRAL", strength: 0.3, confidence: 0.7, weight: 1.8, contribution: 0.000, evidence: "Maintained guide, mixed tone" },
      ],
    },
    {
      ticker: "MRVL",
      score: 0.00,
      platforms_reporting: ["earnings"],
      platforms_failed: [],
      breakdown: [
        { sensor: "earnings", direction: "BEAR", strength: 0.5, confidence: 0.7, weight: 1.8, contribution: -0.630, evidence: "Miss + lowered guidance" },
      ],
    },
  ],
};
