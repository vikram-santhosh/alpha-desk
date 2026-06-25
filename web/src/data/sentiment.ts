import type { SentimentTicker, SparklinePoint } from "../types";

function generateVolume(seed = 1000): SparklinePoint[] {
  const points: SparklinePoint[] = [];
  let value = seed;
  for (let i = 0; i < 30; i++) {
    value = Math.max(100, value * (1 + (Math.random() - 0.5) * 0.2));
    points.push({ value });
  }
  return points;
}

export const sentimentTickers: SentimentTicker[] = [
  {
    ticker: "NVDA",
    socialScore: 78,
    bullishPct: 68,
    bearishPct: 32,
    socialVolume: generateVolume(4500),
    priceChangePct: -2.4,
    divergence: "bullish",
    topInfluencerPosts: [
      "Bullish thread on Blackwell ramp and inference share.",
      "Bearish take: export-control risk to China revenue.",
    ],
  },
  {
    ticker: "GEV",
    socialScore: 64,
    bullishPct: 72,
    bearishPct: 28,
    socialVolume: generateVolume(1200),
    priceChangePct: 4.1,
    divergence: "bullish",
    topInfluencerPosts: [
      "Datacenter power demand narrative gaining traction.",
      "Grid interconnection backlog discussed widely.",
    ],
  },
  {
    ticker: "UBER",
    socialScore: 42,
    bullishPct: 35,
    bearishPct: 65,
    socialVolume: generateVolume(2100),
    priceChangePct: -5.2,
    divergence: "bearish",
    topInfluencerPosts: [
      "Disappointment on autonomous timeline.",
      "Delivery growth deceleration thesis resurfacing.",
    ],
  },
  {
    ticker: "MRVL",
    socialScore: 81,
    bullishPct: 74,
    bearishPct: 26,
    socialVolume: generateVolume(2800),
    priceChangePct: 8.7,
    divergence: "bullish",
    topInfluencerPosts: [
      "Custom silicon tailwind from cloud customers.",
      "AI networking share gains vs Broadcom.",
    ],
  },
  {
    ticker: "META",
    socialScore: 55,
    bullishPct: 48,
    bearishPct: 52,
    socialVolume: generateVolume(3200),
    priceChangePct: 1.2,
    divergence: "none",
    topInfluencerPosts: [
      "Mixed: Reality Labs losses vs ad rebound.",
    ],
  },
];
