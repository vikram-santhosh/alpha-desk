import type { CouncilRunRequest, IdeaScoutResult, ModelOption, PortfolioSnapshot } from "./types";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(apiUrl(path));
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchCouncilModels() {
  return getJson<ModelOption[]>("/api/council/models");
}

export function fetchPortfolioSnapshot() {
  return getJson<PortfolioSnapshot>("/api/portfolio");
}

export function fetchTodayIdeas(limit = 12, mode: "top_buys" | "new_discoveries" = "top_buys") {
  const params = new URLSearchParams({ limit: String(limit), mode });
  return getJson<IdeaScoutResult>(`/api/ideas/today?${params.toString()}`);
}

export function councilStreamUrl(request: CouncilRunRequest) {
  const params = new URLSearchParams({ ticker: request.ticker });
  if (request.models.length > 0) {
    params.set("models", request.models.join(","));
  }
  return apiUrl(`/api/council/stream?${params.toString()}`);
}
