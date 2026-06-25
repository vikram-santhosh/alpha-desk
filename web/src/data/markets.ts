import type { PredictionMarket, SparklinePoint } from "../types";

function generateProbability(seed: number): SparklinePoint[] {
  const points: SparklinePoint[] = [];
  let value = seed;
  for (let i = 0; i < 7; i++) {
    value = Math.max(5, Math.min(95, value + (Math.random() - 0.5) * 10));
    points.push({ value });
  }
  return points;
}

export const predictionMarkets: PredictionMarket[] = [
  {
    id: "pm-1",
    question: "Fed cuts rates at least once by July 2026?",
    probability: 42,
    modelEstimate: 55,
    sevenDaySparkline: generateProbability(38),
    position: "yes",
    resolutionDate: "2026-07-31",
    source: "Kalshi",
  },
  {
    id: "pm-2",
    question: "NVDA revenue beats whisper by >2% in Q1 FY27?",
    probability: 67,
    modelEstimate: 72,
    sevenDaySparkline: generateProbability(60),
    position: null,
    resolutionDate: "2026-05-21",
    source: "Kalshi",
  },
  {
    id: "pm-3",
    question: "S&P 500 ends 2026 above 6,500?",
    probability: 58,
    modelEstimate: 48,
    sevenDaySparkline: generateProbability(55),
    position: "no",
    resolutionDate: "2026-12-31",
    source: "Polymarket",
  },
  {
    id: "pm-4",
    question: "Any G7 central bank cuts >75 bps in 2026?",
    probability: 31,
    modelEstimate: 28,
    sevenDaySparkline: generateProbability(35),
    position: "yes",
    resolutionDate: "2026-12-31",
    source: "Polymarket",
  },
];
