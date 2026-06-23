export type ThemeAccent = "cyan" | "emerald" | "amber" | "rose" | "violet" | "blue";

export type AlertSeverity = "critical" | "warning" | "info";
export type AlertState = "new" | "acknowledged" | "muted" | "resolved";

export interface SparklinePoint {
  value: number;
  label?: string;
}

export interface SleevePosition {
  ticker: string;
  name: string;
  weight: number;
  theme: string;
  price: number;
  changePct: number;
  value: number;
  shares: number;
  sparkline: SparklinePoint[];
  thesis?: string;
  thesisStatus?: "strong" | "intact" | "under_review" | "degraded" | "invalidated";
  breach?: AlertSeverity | null;
}

export interface PortfolioSummary {
  totalValue: number;
  dayPnl: number;
  dayPnlPct: number;
  cash: number;
  activeBreachCount: number;
  activeSignalCount: number;
  asOf: string;
}

export interface Alert {
  id: string;
  ticker: string;
  metric: string;
  severity: AlertSeverity;
  state: AlertState;
  currentValue: number;
  thresholdValue: number;
  firstTriggeredAt: string;
  resolvedAt?: string;
  description: string;
}

export interface MacroTheme {
  id: string;
  title: string;
  status: "risk_on" | "neutral" | "risk_off";
  confidence: number;
  trend: "up" | "down" | "flat";
  bullets: string[];
  agent: string;
  scannedAt: string;
}

export interface MacroRegime {
  call: string;
  score: number; // 0-100, higher = more risk-on
  confidence: number; // 0-100, model confidence in the regime call
  rationale: string;
  agent: string;
  scannedAt: string;
}

export interface SentimentTicker {
  ticker: string;
  socialScore: number;
  bullishPct: number;
  bearishPct: number;
  socialVolume: SparklinePoint[];
  priceChangePct: number;
  divergence: "bullish" | "bearish" | "none";
  topInfluencerPosts: string[];
}

export interface ResearchReport {
  id: string;
  title: string;
  tickers: string[];
  agent: string;
  tier: "quick" | "deep";
  freshness: string;
  summary: string;
  verdict: string;
  confidence: number;
  sections: { heading: string; content: string }[];
}

export interface Moonshot {
  id: string;
  ticker: string;
  name: string;
  sector: string;
  thesis: string;
  conviction: number;
  asymmetry: { downside: number; upside: number };
  whyNow: string;
}

export interface PredictionMarket {
  id: string;
  question: string;
  probability: number;
  modelEstimate: number;
  sevenDaySparkline: SparklinePoint[];
  position?: "yes" | "no" | null;
  resolutionDate: string;
  source: string;
}

export interface DailyBriefSection {
  type: "breaches" | "movers" | "macro" | "sentiment" | "research" | "moonshot";
  title: string;
  salience: number;
  content: unknown;
}

export interface CommandResult {
  answer: string;
  agent: string;
  confidence: number;
}

export interface DigestSection {
  title: string;
  markdown: string;
}
