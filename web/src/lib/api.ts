import type {
  Alert,
  BriefRunResult,
  BriefRunType,
  CommandResult,
  CouncilResult,
  CouncilRunRequest,
  DailyBriefSection,
  DeploymentPlanInputs,
  DeploymentPlanResult,
  IdeaScoutResult,
  MacroRegime,
  MacroTheme,
  ModelOption,
  Moonshot,
  PortfolioSnapshot,
  PortfolioSummary,
  PredictionMarket,
  ResearchReport,
  ScoutProgress,
  SentimentTicker,
  SleevePosition,
} from "../types";
import { positions, portfolioSummary } from "../data/portfolio";
import { alerts } from "../data/alerts";
import { macroRegime, macroThemes } from "../data/macro";
import { sentimentTickers } from "../data/sentiment";
import { researchReports } from "../data/research";
import { moonshots } from "../data/moonshots";
import { predictionMarkets } from "../data/markets";
import { mockDeploymentPlan } from "../data/deployment";
import { mockIdeaScout } from "../data/scout";
import { mockBrief } from "../data/brief";

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

const timeoutSeconds = (ms: number) => Math.round(ms / 1000);

/**
 * fetch with a timeout that fails with a clear, actionable message instead of
 * the browser's opaque "signal is aborted without reason" DOMException — and
 * distinguishes a slow/hung backend from one that isn't reachable at all.
 */
async function fetchWithTimeout(
  path: string,
  init: RequestInit = {},
  timeoutMs = 15_000
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(new DOMException(`Timed out after ${timeoutSeconds(timeoutMs)}s`, "TimeoutError")),
    timeoutMs
  );
  try {
    return await fetch(apiUrl(path), { ...init, signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && (err.name === "TimeoutError" || err.name === "AbortError")) {
      throw new Error(
        `Request to ${path} timed out after ${timeoutSeconds(timeoutMs)}s — is the backend running at ${API_BASE_URL}?`
      );
    }
    if (err instanceof TypeError) {
      // fetch throws TypeError ("Failed to fetch") when the host can't be reached.
      throw new Error(`Could not reach the backend at ${API_BASE_URL}. Start it with: python run_api.py`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function getJson<T>(path: string, timeoutMs = 15_000): Promise<T> {
  const response = await fetchWithTimeout(path, {}, timeoutMs);
  if (!response.ok) {
    throw new Error(`Backend request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: unknown, timeoutMs = 15_000): Promise<T> {
  const response = await fetchWithTimeout(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    timeoutMs
  );
  if (!response.ok) {
    let detail = `Backend request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Keep status-based detail.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
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

export async function runBrief(runType: BriefRunType): Promise<BriefRunResult> {
  if (USE_MOCKS) return delay({ ...mockBrief, run_type: runType, saved_at: new Date().toISOString() }, 800);
  return postJson<BriefRunResult>("/api/brief/run", { run_type: runType }, 620_000);
}

export async function fetchLatestBrief(): Promise<BriefRunResult | null> {
  if (USE_MOCKS) return delay(mockBrief, 250);
  const response = await fetchWithTimeout("/api/brief/runs/latest", {}, 15_000);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Backend request failed: ${response.status}`);
  return (await response.json()) as BriefRunResult;
}

export async function runDeploymentPlan(
  inputs: DeploymentPlanInputs
): Promise<DeploymentPlanResult> {
  if (USE_MOCKS) {
    return delay(
      {
        ...mockDeploymentPlan,
        saved_at: new Date().toISOString(),
        generated_at: new Date().toISOString(),
        mandate: {
          ...mockDeploymentPlan.mandate,
          capital: inputs.capital,
          return_target: inputs.return_target ?? mockDeploymentPlan.mandate.return_target,
          account_type: inputs.account_type ?? mockDeploymentPlan.mandate.account_type,
          constraints: inputs.constraints ?? mockDeploymentPlan.mandate.constraints,
          tracked_themes: inputs.themes?.length
            ? inputs.themes
            : mockDeploymentPlan.mandate.tracked_themes,
        },
      },
      900
    );
  }
  // Single long-form synthesis call — can take a minute or more, so allow a wide timeout.
  return postJson<DeploymentPlanResult>("/api/deployment/plan", inputs, 620_000);
}

export interface DeploymentStreamHandlers {
  onProgress?: (message: string) => void;
  onChunk: (delta: string) => void;
  onDone: (result: DeploymentPlanResult) => void;
  onError: (message: string) => void;
}

/**
 * Stream the deployment report as it's written. Returns a cancel function.
 * In mock mode it simulates token streaming; otherwise it uses an SSE
 * EventSource and closes it on done/error so it never auto-reconnects (which
 * would re-trigger a billable synthesis).
 */
export function streamDeploymentPlan(
  inputs: DeploymentPlanInputs,
  handlers: DeploymentStreamHandlers
): () => void {
  if (USE_MOCKS) {
    let cancelled = false;
    const md = mockDeploymentPlan.markdown;
    const parts = md.match(/[\s\S]{1,90}/g) ?? [md];
    let i = 0;
    handlers.onProgress?.("Writing the report…");
    const tick = () => {
      if (cancelled) return;
      if (i < parts.length) {
        handlers.onChunk(parts[i++]);
        setTimeout(tick, 30);
      } else {
        handlers.onDone({ ...mockDeploymentPlan, markdown: md, saved_at: new Date().toISOString() });
      }
    };
    setTimeout(tick, 150);
    return () => {
      cancelled = true;
    };
  }

  const params = new URLSearchParams({ capital: String(inputs.capital) });
  if (inputs.return_target) params.set("return_target", inputs.return_target);
  if (inputs.account_type) params.set("account_type", inputs.account_type);
  if (inputs.constraints) params.set("constraints", inputs.constraints);
  if (inputs.themes?.length) params.set("themes", inputs.themes.join(","));

  const source = new EventSource(apiUrl(`/api/deployment/stream?${params.toString()}`));
  let markdown = "";
  let finished = false;

  const finish = () => {
    finished = true;
    source.close();
  };

  source.addEventListener("progress", (event) => {
    try {
      handlers.onProgress?.(JSON.parse((event as MessageEvent).data).message);
    } catch {
      /* ignore malformed progress */
    }
  });
  source.addEventListener("chunk", (event) => {
    try {
      const delta = JSON.parse((event as MessageEvent).data).delta as string;
      markdown += delta;
      handlers.onChunk(delta);
    } catch {
      /* ignore malformed chunk */
    }
  });
  source.addEventListener("error", (event) => {
    if (finished) return;
    let message = "Deployment stream failed";
    const data = (event as MessageEvent).data;
    if (data) {
      try {
        message = JSON.parse(data).message ?? message;
      } catch {
        /* keep default */
      }
    } else {
      message = `Could not reach the streaming backend at ${API_BASE_URL}.`;
    }
    finish();
    handlers.onError(message);
  });
  source.addEventListener("done", (event) => {
    let done: Record<string, unknown> = {};
    try {
      done = JSON.parse((event as MessageEvent).data);
    } catch {
      /* tolerate */
    }
    finish();
    handlers.onDone({
      run_id: done.run_id as number | undefined,
      saved_at: (done.saved_at as string) ?? new Date().toISOString(),
      generated_at: (done.generated_at as string) ?? new Date().toISOString(),
      model: (done.model as string) ?? "openrouter",
      markdown,
      mandate: {
        capital: inputs.capital,
        return_target: inputs.return_target,
        account_type: inputs.account_type,
        constraints: inputs.constraints,
        tracked_themes: inputs.themes,
      },
      diagnosis: (done.stats as Record<string, unknown>) ?? {},
      stats: (done.stats as Record<string, unknown>) ?? {},
      cost_usd: (done.cost_usd as number) ?? 0,
      degraded_reasons: (done.degraded_reasons as string[]) ?? [],
    });
  });

  return finish;
}

export async function fetchLatestDeploymentPlan(): Promise<DeploymentPlanResult | null> {
  if (USE_MOCKS) return delay(mockDeploymentPlan, 250);
  const response = await fetchWithTimeout("/api/deployment/runs/latest", {}, 15_000);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Backend request failed: ${response.status}`);
  return (await response.json()) as DeploymentPlanResult;
}

export async function fetchLatestCouncilRun(ticker?: string): Promise<CouncilResult | null> {
  const params = new URLSearchParams();
  if (ticker) params.set("ticker", ticker);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetchWithTimeout(`/api/council/runs/latest${suffix}`, {}, 15_000);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Backend request failed: ${response.status}`);
  return (await response.json()) as CouncilResult;
}

export async function fetchPortfolioSnapshot(): Promise<PortfolioSnapshot> {
  return getJson<PortfolioSnapshot>("/api/portfolio", 15_000);
}

export async function fetchAlerts(): Promise<Alert[]> {
  if (USE_MOCKS) return delay([...alerts]);
  return getJson<Alert[]>("/api/alerts", 15_000);
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
  if (USE_MOCKS) return delay({ ...mockIdeaScout, scout_mode: mode }, 700);
  const params = new URLSearchParams({ limit: String(limit), mode });
  return getJson<IdeaScoutResult>(`/api/ideas/today?${params.toString()}`, 240_000);
}

// Live stage progress of the in-flight Alpha Scout pipeline (for the stage view).
export async function fetchScoutProgress(): Promise<ScoutProgress> {
  if (USE_MOCKS) return { active: false, stages: [] };
  return getJson<ScoutProgress>(`/api/ideas/progress`, 8_000);
}

// Instant deterministic Top Buys from the score engine (no LLM / Alpha Scout).
export async function fetchFastTopBuys(limit = 10): Promise<IdeaScoutResult> {
  if (USE_MOCKS) {
    return delay({ ...mockIdeaScout, scout_mode: "top_buys", universe: "Deterministic score-engine snapshot" }, 300);
  }
  return getJson<IdeaScoutResult>(`/api/ideas/fast?limit=${limit}`, 60_000);
}

export async function fetchLatestIdeaScout(
  mode?: "top_buys" | "new_discoveries"
): Promise<IdeaScoutResult | null> {
  if (USE_MOCKS) return delay({ ...mockIdeaScout, scout_mode: mode ?? mockIdeaScout.scout_mode }, 250);
  const params = new URLSearchParams();
  if (mode) params.set("mode", mode);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetchWithTimeout(`/api/ideas/runs/latest${suffix}`, {}, 15_000);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Backend request failed: ${response.status}`);
  return (await response.json()) as IdeaScoutResult;
}

export async function fetchSentimentTickers(): Promise<SentimentTicker[]> {
  if (USE_MOCKS) return delay([...sentimentTickers]);
  return getJson<SentimentTicker[]>("/api/sentiment", 20_000);
}

export async function fetchResearchReports(): Promise<ResearchReport[]> {
  if (USE_MOCKS) return delay([...researchReports]);
  return getJson<ResearchReport[]>("/api/research", 15_000);
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
  if (USE_MOCKS) return delay([...predictionMarkets]);
  return getJson<PredictionMarket[]>("/api/markets", 30_000);
}

export async function fetchDailyBrief(): Promise<DailyBriefSection[]> {
  const latest = await fetchLatestBrief();
  if (!latest) return [];
  return [
    {
      type: "research",
      title: "Latest Daily Brief",
      salience: 100,
      content: latest,
    },
  ];
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
