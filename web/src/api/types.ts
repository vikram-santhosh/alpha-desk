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

export interface CouncilRunRequest {
  ticker: string;
  models: string[];
}

export interface DoneEvent {
  cost_usd: number;
  degraded_reasons: string[];
}

export type CouncilEvent =
  | { type: "panel_started"; data: { ticker: string; models: string[] } }
  | { type: "panel_model_result"; data: PanelVerdict }
  | { type: "judge_result"; data: JudgeAnalysis }
  | { type: "verdict"; data: Verdict }
  | { type: "done"; data: DoneEvent }
  | { type: "error"; data: { message: string } };
