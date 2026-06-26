import type {
  Alert,
  CommandResult,
  CouncilResult,
  CouncilRunRequest,
  DailyBriefSection,
  IdeaScoutResult,
  MacroRegime,
  MacroTheme,
  ModelOption,
  Moonshot,
  PortfolioSnapshot,
  PortfolioSummary,
  PredictionMarket,
  ResearchReport,
  SentimentTicker,
  SleevePosition,
  TopBuysResult,
} from "../types";
import { positions, portfolioSummary } from "../data/portfolio";
import { alerts } from "../data/alerts";
import { macroRegime, macroThemes } from "../data/macro";
import { sentimentTickers } from "../data/sentiment";
import { researchReports } from "../data/research";
import { moonshots } from "../data/moonshots";
import { predictionMarkets } from "../data/markets";
import { topBuysMock } from "../data/topbuys";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "1";

interface MacroDashboardPayload {
  regime: MacroRegime;
  themes: MacroTheme[];
  degraded_reasons?: string[];
}

interface BackendTopIdea {
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

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`;
}

async function getJson<T>(path: string, timeoutMs = 15_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(apiUrl(path), { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`Backend request failed: ${response.status}`);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export function backendUrl(path: string) {
  return apiUrl(path);
}

export function councilStreamUrl(request: CouncilRunRequest) {
  const params = new URLSearchParams({ ticker: request.ticker });
  if (request.models.length > 0) {
    params.set("models", request.models.join(","));
  }
  if (request.source) params.set("source", request.source);
  if (request.idea_run_id) params.set("idea_run_id", String(request.idea_run_id));
  if (request.score_snapshot_id) params.set("score_snapshot_id", request.score_snapshot_id);
  return apiUrl(`/api/council/stream?${params.toString()}`);
}

function delay<T>(value: T, ms = 400): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

function mockMacroDashboard(reason: string): MacroDashboardPayload {
  return {
    regime: {
      ...macroRegime,
      source: "mock",
      sourceDetail: reason,
      degradedReasons: [reason],
    },
    themes: [...macroThemes],
    degraded_reasons: [reason],
  };
}

let macroDashboardRequest: Promise<MacroDashboardPayload> | null = null;

async function fetchMacroDashboard(): Promise<MacroDashboardPayload> {
  if (USE_MOCKS) {
    return delay(mockMacroDashboard("VITE_USE_MOCKS=1; dashboard is using local macro fixtures."), 250);
  }
  if (macroDashboardRequest) {
    return macroDashboardRequest;
  }
  macroDashboardRequest = getJson<MacroDashboardPayload>("/api/macro", 20_000)
    .then((payload) => {
      const degradedReasons = payload.degraded_reasons ?? payload.regime.degradedReasons ?? [];
      return {
        ...payload,
        regime: {
          ...payload.regime,
          source: "backend" as const,
          degradedReasons,
          sourceDetail:
            payload.regime.sourceDetail ??
            (degradedReasons.length > 0
              ? `Backend degraded: ${degradedReasons[0]}`
              : "Backend live data from FastAPI."),
        },
      };
    })
    .finally(() => {
      macroDashboardRequest = null;
    });
  return macroDashboardRequest;
}

function mockMoonshots(reason: string): Moonshot[] {
  return moonshots.map((moonshot) => ({
    ...moonshot,
    source: "mock",
    sourceDetail: reason,
  }));
}

function ideaToMoonshot(idea: BackendTopIdea, scoutMode: string, degradedReasons: string[]): Moonshot {
  const conviction = Math.max(0, Math.min(100, Math.round(idea.score * 100)));
  const downside = Math.max(10, Math.min(55, Math.round(60 - conviction / 2)));
  const upside = Math.max(40, Math.min(220, Math.round(55 + conviction * 1.5)));
  const sector = idea.theme.split("·").at(-1)?.trim() || idea.theme || "Recommendation";
  return {
    id: `backend-${idea.ticker.toLowerCase()}-${idea.rank}`,
    ticker: idea.ticker,
    name: idea.company || idea.ticker,
    sector,
    thesis: idea.thesis,
    conviction,
    asymmetry: { downside, upside },
    whyNow: idea.catalysts.length > 0 ? idea.catalysts.join(" · ") : idea.horizon,
    source: "backend",
    sourceDetail:
      degradedReasons.length > 0
        ? `Alpha Scout ${scoutMode} with degradation: ${degradedReasons[0]}`
        : `Alpha Scout ${scoutMode} via FastAPI.`,
  };
}

export async function fetchPortfolioSummary(): Promise<PortfolioSummary> {
  return delay({ ...portfolioSummary, asOf: new Date().toISOString() });
}

export async function fetchPositions(): Promise<SleevePosition[]> {
  return delay([...positions]);
}

export async function fetchCouncilModels(): Promise<ModelOption[]> {
  return getJson<ModelOption[]>("/api/council/models", 15_000);
}

export async function fetchLatestCouncilRun(ticker?: string): Promise<CouncilResult | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  const params = new URLSearchParams();
  if (ticker) params.set("ticker", ticker);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  try {
    const response = await fetch(apiUrl(`/api/council/runs/latest${suffix}`), { signal: controller.signal });
    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      throw new Error(`Backend request failed: ${response.status}`);
    }
    return (await response.json()) as CouncilResult;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchPortfolioSnapshot(): Promise<PortfolioSnapshot> {
  return getJson<PortfolioSnapshot>("/api/portfolio", 15_000);
}

export async function fetchAlerts(): Promise<Alert[]> {
  return delay([...alerts]);
}

export async function fetchMacroRegime(): Promise<MacroRegime> {
  const dashboard = await fetchMacroDashboard();
  return dashboard.regime;
}

export async function fetchMacroThemes(): Promise<MacroTheme[]> {
  const dashboard = await fetchMacroDashboard();
  return dashboard.themes;
}

export async function fetchIdeaScout(
  mode: "top_buys" | "new_discoveries" = "new_discoveries",
  limit = 10
): Promise<IdeaScoutResult> {
  const params = new URLSearchParams({ limit: String(limit), mode });
  return getJson<IdeaScoutResult>(`/api/ideas/today?${params.toString()}`, 240_000);
}

export async function fetchLatestIdeaScout(
  mode?: "top_buys" | "new_discoveries"
): Promise<IdeaScoutResult | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  const params = new URLSearchParams();
  if (mode) params.set("mode", mode);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  try {
    const response = await fetch(apiUrl(`/api/ideas/runs/latest${suffix}`), { signal: controller.signal });
    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      throw new Error(`Backend request failed: ${response.status}`);
    }
    return (await response.json()) as IdeaScoutResult;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchSentimentTickers(): Promise<SentimentTicker[]> {
  return delay([...sentimentTickers]);
}

export async function fetchResearchReports(): Promise<ResearchReport[]> {
  return delay([...researchReports]);
}

export async function runResearchQuery(query: string): Promise<ResearchReport> {
  // Simulate a streamed/deep research run.
  return delay(
    {
      id: `rpt-live-${Date.now()}`,
      title: `Live research: ${query}`,
      tickers: ["AI"],
      agent: "Multi-Agent Research",
      tier: "deep",
      freshness: "just now",
      summary:
        "Initiating cross-agent research across news, fundamentals, and macro signals. Preliminary scan suggests concentrated AI-capex exposure with elevated geopolitical risk.",
      verdict: "Under review",
      confidence: 48,
      sections: [
        { heading: "Thesis", content: "Query intersects with existing high-conviction AI compute theme." },
        { heading: "Risks", content: "Geopolitical tail risk and rate sensitivity elevated." },
        { heading: "Verdict", content: "Hold current exposure; await further data." },
      ],
    },
    1200
  );
}

export async function fetchMoonshots(): Promise<Moonshot[]> {
  if (USE_MOCKS) {
    return delay(mockMoonshots("VITE_USE_MOCKS=1; dashboard is using local recommendation fixtures."), 250);
  }

  const result = await fetchIdeaScout("top_buys", 10);
  const ideas = result.ideas.map((idea) =>
    ideaToMoonshot(idea, result.scout_mode, result.degraded_reasons ?? [])
  );
  if (ideas.length > 0) {
    return ideas;
  }
  throw new Error("Backend Alpha Scout returned no ideas.");
}

export async function fetchPredictionMarkets(): Promise<PredictionMarket[]> {
  return delay([...predictionMarkets]);
}

export async function fetchDailyBrief(): Promise<DailyBriefSection[]> {
  const [regime, liveMoonshots] = await Promise.all([fetchMacroRegime(), fetchMoonshots()]);
  const activeAlerts = alerts.filter((a) => a.state !== "resolved");
  const sections: DailyBriefSection[] = [];

  if (activeAlerts.length > 0) {
    sections.push({
      type: "breaches",
      title: "Active Breaches",
      salience: 100,
      content: activeAlerts,
    });
  }

  const topMovers = [...positions]
    .filter((p) => p.ticker !== "SGOV")
    .sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct))
    .slice(0, 4);

  sections.push({
    type: "movers",
    title: "Top Movers",
    salience: 90,
    content: topMovers,
  });

  sections.push({
    type: "macro",
    title: "Macro Regime",
    salience: 80,
    content: regime,
  });

  const divergences = sentimentTickers.filter((s) => s.divergence !== "none").slice(0, 3);
  sections.push({
    type: "sentiment",
    title: "Street Ear Pulse",
    salience: 70,
    content: divergences,
  });

  const latestResearch = researchReports[0];
  sections.push({
    type: "research",
    title: "Fresh Research",
    salience: 60,
    content: latestResearch,
  });

  const moonshot = liveMoonshots[0] ?? mockMoonshots("Mock fallback: no backend recommendation available.")[0];
  sections.push({
    type: "moonshot",
    title: moonshot.source === "backend" ? "Backend Recommendation" : "Moonshot of the Day",
    salience: 40,
    content: moonshot,
  });

  return delay(sections.sort((a, b) => b.salience - a.salience));
}

export async function fetchTopBuys(): Promise<TopBuysResult> {
  if (USE_MOCKS) {
    return delay({ ...topBuysMock, source: "mock" as const }, 300);
  }
  try {
    const result = await getJson<TopBuysResult>("/api/score/top-buys", 60_000);
    return { ...result, source: "backend" as const };
  } catch {
    return { ...topBuysMock, source: "mock" as const };
  }
}

export async function runScoreEngine(): Promise<TopBuysResult> {
  if (USE_MOCKS) {
    return delay({ ...topBuysMock, source: "mock" as const }, 1200);
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120_000);
    try {
      const response = await fetch(apiUrl("/api/score/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ top_n: 10, depth: "standard" }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Score run failed: ${response.status}`);
      const result = await response.json() as TopBuysResult;
      return { ...result, source: "backend" as const };
    } finally {
      clearTimeout(timer);
    }
  } catch {
    return { ...topBuysMock, source: "mock" as const };
  }
}

export async function askAlphaDesk(question: string): Promise<CommandResult> {
  return delay(
    {
      answer: `Based on the latest signals, ${question.toLowerCase()} intersects with our AI-capex and power/grid themes. The portfolio is overweight AI compute and underweight energy/defense. Consider reviewing concentration in NVDA/TSM and adding exposure to GEV or uranium miners as a hedge.`,
      agent: "Advisor",
      confidence: 64,
    },
    800
  );
}
