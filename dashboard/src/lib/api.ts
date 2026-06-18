import type {
  Alert,
  CommandResult,
  DailyBriefSection,
  MacroRegime,
  MacroTheme,
  Moonshot,
  PortfolioSummary,
  PredictionMarket,
  ResearchReport,
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

function delay<T>(value: T, ms = 400): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

export async function fetchPortfolioSummary(): Promise<PortfolioSummary> {
  return delay({ ...portfolioSummary, asOf: new Date().toISOString() });
}

export async function fetchPositions(): Promise<SleevePosition[]> {
  return delay([...positions]);
}

export async function fetchAlerts(): Promise<Alert[]> {
  return delay([...alerts]);
}

export async function fetchMacroRegime(): Promise<MacroRegime> {
  return delay({ ...macroRegime });
}

export async function fetchMacroThemes(): Promise<MacroTheme[]> {
  return delay([...macroThemes]);
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
  return delay([...moonshots]);
}

export async function fetchPredictionMarkets(): Promise<PredictionMarket[]> {
  return delay([...predictionMarkets]);
}

export async function fetchDailyBrief(): Promise<DailyBriefSection[]> {
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
    content: macroRegime,
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

  const moonshot = moonshots[0];
  sections.push({
    type: "moonshot",
    title: "Moonshot of the Day",
    salience: 40,
    content: moonshot,
  });

  return delay(sections.sort((a, b) => b.salience - a.salience));
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
