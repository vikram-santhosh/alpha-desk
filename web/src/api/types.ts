export type Rating = "Buy" | "Overweight" | "Hold" | "Underweight" | "Sell";

export interface PanelVerdict {
  model_id: string;
  label: string;
  rating: Rating;
  confidence: number;
  thesis: string;
  dissent: boolean;
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
  panel: PanelVerdict[];
  judge: JudgeAnalysis;
  verdict: Verdict;
  cost_usd: number;
  degraded_reasons: string[];
  execution_mode: string;
}

export interface Position {
  ticker: string;
  weight_pct: number;
  rating?: Rating;
}

export interface PortfolioSnapshot {
  positions: Position[];
  top_holding_pct: number;
  top3_pct: number;
  concentration_flag: boolean;
}

export interface ModelOption {
  model_id: string;
  label: string;
  provider: string;
  enabled: boolean;
}

export interface TopIdea {
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
  as_of: string;
  universe: string;
  scout_mode: string;
  ideas: TopIdea[];
  data_source_checks: DataSourceCheck[];
  audit: IdeaScoutAudit;
  cost_usd: number;
  degraded_reasons: string[];
  disclaimer: string;
}

export interface CouncilRunRequest {
  ticker: string;
  models: string[];
}

export interface DoneEvent {
  cost_usd: number;
  degraded_reasons: string[];
  council_mode: string;
}

export type CouncilEvent =
  | { type: "panel_started"; data: { ticker: string; models: string[] } }
  | { type: "panel_model_result"; data: PanelVerdict }
  | { type: "judge_result"; data: JudgeAnalysis }
  | { type: "verdict"; data: Verdict }
  | { type: "done"; data: DoneEvent }
  | { type: "error"; data: { message: string } };
