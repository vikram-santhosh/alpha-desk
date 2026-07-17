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
  source?: "backend" | "mock";
  sourceDetail?: string;
  degradedReasons?: string[];
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
  source?: "backend" | "mock";
  sourceDetail?: string;
  scoutRunId?: number;
  scoutMode?: string;
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

export type BriefRunType = "morning_full" | "evening_wrap" | "weekend" | "auto";

export interface BriefRunResult {
  run_id?: number;
  saved_at?: string;
  run_type: string;
  formatted: string;
  sections: Record<string, unknown>;
  stats: Record<string, unknown>;
  degraded_reasons: string[];
}

export interface DeploymentPlanInputs {
  capital: number;
  return_target?: string;
  account_type?: string;
  constraints?: string;
  themes?: string[];
}

export interface DeploymentPlanResult {
  run_id?: number;
  saved_at?: string;
  generated_at: string;
  model: string;
  markdown: string;
  mandate: Record<string, unknown>;
  diagnosis: Record<string, unknown>;
  stats: Record<string, unknown>;
  cost_usd: number;
  degraded_reasons: string[];
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

export type Rating = "Buy" | "Overweight" | "Hold" | "Underweight" | "Sell";

export interface ModelOption {
  model_id: string;
  label: string;
  provider: string;
  enabled: boolean;
}

export interface DimensionScore {
  name: string;
  score: number;
  weight: number;
  contribution: number;
}

export interface IdeaDebug {
  composite: number;
  dimensions: DimensionScore[];
  factors: string[];
  fundamentals: Record<string, number | string | null>;
  source: string;
  corroboration_count: number;
  corroborating_sources: string[];
  synthesis_source?: string | null;
}

export interface BackendTopIdea {
  rank: number;
  ticker: string;
  company: string;
  theme: string;
  score: number;
  horizon: string;
  thesis: string;
  catalysts: string[];
  risks: string[];
  source: string;
  debug?: IdeaDebug | null;
}

export type ScoutStageStatus = "pending" | "running" | "done" | "skipped" | "error";

export interface ScoutStage {
  key: string;
  label: string;
  status: ScoutStageStatus;
  detail: string;
  ts?: number | null;
}

export interface ScoutProgress {
  active: boolean;
  mode?: string | null;
  run_id?: string | null;
  started_at?: number | null;
  updated_at?: number | null;
  finished_at?: number | null;
  current?: string | null;
  error?: string | null;
  stages: ScoutStage[];
}

export type DataSourceStatus = "validated" | "configured" | "unavailable";

export interface DataSourceCheck {
  source: string;
  status: DataSourceStatus;
  detail: string;
  checked_at: string;
}

export interface IdeaScoutAudit {
  mode: string;
  source_counts: Record<string, number>;
  raw_candidates: number;
  unique_candidates: number;
  capped_candidates: number;
  existing_universe_count: number;
  excluded_existing: Array<Record<string, unknown>>;
  tracked_ticker_checks: Record<string, Record<string, unknown>>;
}

export interface IdeaScoutResult {
  run_id?: number;
  saved_at?: string;
  as_of: string;
  universe: string;
  scout_mode: string;
  ideas: BackendTopIdea[];
  data_source_checks: DataSourceCheck[];
  audit: IdeaScoutAudit;
  cost_usd: number;
  degraded_reasons: string[];
  disclaimer: string;
}

export interface BackendPosition {
  ticker: string;
  weight_pct: number;
  rating?: Rating;
}

export interface PortfolioSnapshot {
  positions: BackendPosition[];
  top_holding_pct: number;
  top3_pct: number;
  concentration_flag: boolean;
}

export interface CouncilRunRequest {
  ticker: string;
  models: string[];
  source?: string;
  idea_run_id?: number;
  score_snapshot_id?: string;
}

export interface PanelVerdict {
  model_id: string;
  label: string;
  rating: Rating;
  confidence: number;
  thesis: string;
  dissent: boolean;
  accepted_claims?: string[];
  rejected_claims?: string[];
  challenges?: string[];
}

export interface CrowdedFlag {
  topic: string;
  note: string;
}

export interface JudgeAnalysis {
  consensus: string[];
  contradictions: string[];
  blind_spots: string[];
  crowded_narrative_flag?: CrowdedFlag;
}

export interface Scenario {
  name: "Bull" | "Base" | "Bear";
  probability: number;
  ret_pct: number;
}

export interface Verdict {
  ticker: string;
  rating: Rating;
  conviction: number;
  conviction_label: string;
  scenarios: Scenario[];
  catalysts: string[];
  risks: string[];
}

export interface CouncilResult {
  run_id?: number;
  saved_at?: string;
  panel: PanelVerdict[];
  judge: JudgeAnalysis;
  verdict: Verdict;
  cost_usd: number;
  degraded_reasons: string[];
  execution_mode: string;
}

export interface DoneEvent {
  cost_usd: number;
  degraded_reasons: string[];
  council_mode: string;
  run_id?: number;
  saved_at?: string;
}

export interface CouncilProgress {
  phase: string;
  message: string;
  model_id?: string;
  completed?: number;
  total?: number;
}

export type CouncilEvent =
  | { type: "panel_started"; data: { ticker: string; models: string[] } }
  | { type: "progress"; data: CouncilProgress }
  | { type: "panel_model_result"; data: PanelVerdict }
  | { type: "judge_result"; data: JudgeAnalysis }
  | { type: "verdict"; data: Verdict }
  | { type: "done"; data: DoneEvent }
  | { type: "error"; data: { message: string } };
