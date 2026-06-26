import type { Moonshot } from "@/types";
import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { fetchIdeaScout, fetchLatestIdeaScout } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlassButton } from "@/components/ui/GlassButton";
import { Rocket, RefreshCw, Orbit, Search } from "lucide-react";
import { MoonshotCard } from "./MoonshotCard";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { DataSourceCheck, IdeaScoutResult } from "@/types";
import { rise } from "@/lib/motion";

const ALL_SECTORS = "All";
type ScoutMode = "new_discoveries" | "top_buys";

function ideaToMoonshot(
  idea: IdeaScoutResult["ideas"][number],
  result: IdeaScoutResult
): Moonshot {
  const conviction = Math.max(0, Math.min(100, Math.round(idea.score * 100)));
  const downside = Math.max(10, Math.min(55, Math.round(60 - conviction / 2)));
  const upside = Math.max(40, Math.min(220, Math.round(55 + conviction * 1.5)));
  const sector = idea.theme.split("·").at(-1)?.trim() || idea.theme || "Recommendation";
  const degradedReasons = result.degraded_reasons ?? [];
  return {
    id: `backend-${idea.ticker.toLowerCase()}-${idea.rank}-${result.scout_mode}`,
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
        ? `Alpha Scout ${result.scout_mode} with degradation: ${degradedReasons[0]}`
        : `Alpha Scout ${result.scout_mode} via FastAPI.`,
    scoutRunId: result.run_id,
    scoutMode: result.scout_mode,
  };
}

function sourceVariant(status: DataSourceCheck["status"]) {
  if (status === "validated") return "success" as const;
  if (status === "configured") return "warning" as const;
  return "critical" as const;
}

function checkNumber(check: Record<string, unknown>, key: string) {
  const value = check[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function checkString(check: Record<string, unknown>, key: string) {
  const value = check[key];
  return typeof value === "string" ? value : null;
}

export default function MoonshotsView() {
  const [moonshots, setMoonshots] = useState<Moonshot[]>([]);
  const [result, setResult] = useState<IdeaScoutResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [hydrating, setHydrating] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSector, setSelectedSector] = useState<string>(ALL_SECTORS);
  const [mode, setMode] = useState<ScoutMode>("top_buys");
  const reducedMotion = useReducedMotion();

  const applyResult = useCallback((data: IdeaScoutResult) => {
    const nextMode = data.scout_mode === "top_buys" ? "top_buys" : "new_discoveries";
    setResult(data);
    setMode(nextMode);
    setMoonshots(data.ideas.map((idea) => ideaToMoonshot(idea, data)));
  }, []);

  useEffect(() => {
    let active = true;
    fetchLatestIdeaScout("top_buys")
      .then((data) => data ?? fetchLatestIdeaScout())
      .then((data) => {
        if (!active || !data) return;
        applyResult(data);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load saved Alpha Scout run");
      })
      .finally(() => {
        if (active) setHydrating(false);
      });
    return () => {
      active = false;
    };
  }, [applyResult]);

  const load = useCallback(async (nextMode: ScoutMode) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchIdeaScout(nextMode, 10);
      applyResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run Alpha Scout");
    } finally {
      setLoading(false);
    }
  }, [applyResult]);

  const sectors = useMemo(
    () => Array.from(new Set(moonshots.map((m) => m.sector))).sort(),
    [moonshots]
  );

  const filtered = useMemo(() => {
    if (selectedSector === ALL_SECTORS) return moonshots;
    return moonshots.filter((m) => m.sector === selectedSector);
  }, [moonshots, selectedSector]);

  const trackedEntries = useMemo(() => {
    if (!result) return [];
    return Object.entries(result.audit.tracked_ticker_checks ?? {})
      .sort(([, a], [, b]) => {
        const aRecommended = a.recommended === true ? 1 : 0;
        const bRecommended = b.recommended === true ? 1 : 0;
        if (aRecommended !== bRecommended) return bRecommended - aRecommended;
        const aRank = checkNumber(a, "rank") ?? Number.MAX_SAFE_INTEGER;
        const bRank = checkNumber(b, "rank") ?? Number.MAX_SAFE_INTEGER;
        return aRank - bRank;
      })
      .slice(0, 12);
  }, [result]);

  return (
    <section className="mx-auto max-w-7xl space-y-6">
      <motion.header
        className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between"
        initial={reducedMotion ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.25, 0.46, 0.45, 0.94] }}
      >
        <div>
          <div className="flex items-center gap-2">
            <Rocket className="h-5 w-5 text-(--color-accent-violet)" aria-hidden="true" />
            <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">
              Alpha Scout
            </h1>
          </div>
          <p className="mt-1 text-sm text-(--color-text-secondary)">
            Backend discovery and top-buy runs from `/api/ideas/today`.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <GlassButton
            variant={mode === "new_discoveries" ? "solid" : "ghost"}
            leftIcon={<Search className="h-4 w-4" />}
            onClick={() => void load("new_discoveries")}
            disabled={loading}
          >
            Run discovery
          </GlassButton>
          <GlassButton
            variant={mode === "top_buys" ? "solid" : "ghost"}
            leftIcon={<RefreshCw className={`h-4 w-4 ${loading && mode === "top_buys" ? "animate-spin" : ""}`} />}
            onClick={() => void load("top_buys")}
            disabled={loading}
          >
            Run top buys
          </GlassButton>
        </div>
      </motion.header>

      {!loading && hydrating && !result ? (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Skeleton className="h-9 w-24" />
            <Skeleton className="h-9 w-28" />
          </div>
          <Skeleton className="h-48" />
        </div>
      ) : !loading && !result && !error ? (
        <GlassCard className="p-8" hoverLift={false}>
          <EmptyState
            title="Choose an Alpha Scout run"
            description="Run discovery for new names outside the tracked universe, or top buys for ranked candidates including tracked tickers."
            icon={<Rocket className="h-6 w-6" />}
            action={{ label: "Run top buys", onClick: () => void load("top_buys") }}
          />
        </GlassCard>
      ) : loading ? (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Skeleton className="h-9 w-16" />
            <Skeleton className="h-9 w-20" />
            <Skeleton className="h-9 w-24" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Skeleton className="h-80" />
            <Skeleton className="h-80" />
            <Skeleton className="h-80" />
            <Skeleton className="h-80" />
          </div>
        </div>
      ) : error ? (
        <GlassCard glow="rose" className="p-6">
          <EmptyState
            title="Alpha Scout unavailable"
            description={error}
            icon={<Orbit className="h-6 w-6" />}
            action={{ label: "Try again", onClick: () => void load(mode) }}
          />
        </GlassCard>
      ) : (
        <>
          {result && (
            <motion.div variants={rise} className="grid gap-4 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
              <GlassCard className="p-5" hoverLift={false}>
                <p className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">Run audit</p>
                <h2 className="mt-2 text-lg font-semibold text-(--color-text-primary)">
                  {result.scout_mode === "new_discoveries" ? "New discoveries" : "Top buys"}
                </h2>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div>
                    <p className="font-mono text-2xl text-(--color-accent-cyan)">{result.audit.raw_candidates}</p>
                    <p className="text-xs text-(--color-text-tertiary)">raw candidates</p>
                  </div>
                  <div>
                    <p className="font-mono text-2xl text-(--color-accent-violet)">{result.audit.capped_candidates}</p>
                    <p className="text-xs text-(--color-text-tertiary)">screened cap</p>
                  </div>
                </div>
                <p className="mt-4 text-xs leading-relaxed text-(--color-text-secondary)">{result.universe}</p>
                {result.run_id && (
                  <p className="mt-2 font-mono text-xs text-(--color-text-tertiary)">
                    saved run #{result.run_id}{result.saved_at ? ` · ${new Date(result.saved_at).toLocaleString()}` : ""}
                  </p>
                )}
                <p className="mt-2 font-mono text-xs text-(--color-accent-emerald)">${result.cost_usd.toFixed(4)} backend cost</p>
                {trackedEntries.length > 0 && (
                  <div className="mt-4">
                    <p className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">Tracked coverage</p>
                    <div className="mt-2 grid gap-2">
                      {trackedEntries.map(([ticker, check]) => {
                        const rank = checkNumber(check, "rank");
                        const composite = checkNumber(check, "composite");
                        const recommendedAs = checkString(check, "recommended_as");
                        const reason = checkString(check, "omission_reason");
                        return (
                          <div
                            key={ticker}
                            className="rounded-md border border-(--color-border-subtle) bg-(--color-surface-glass) px-3 py-2"
                            title={reason ?? undefined}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <span className="font-mono text-xs text-(--color-text-primary)">{ticker}</span>
                              <span className="text-xs text-(--color-text-tertiary)">
                                {recommendedAs ? recommendedAs : rank ? `rank ${rank}` : "not ranked"}
                                {composite ? ` · ${composite.toFixed(1)}` : ""}
                              </span>
                            </div>
                            {reason && <p className="mt-1 line-clamp-2 text-xs text-(--color-text-secondary)">{reason}</p>}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </GlassCard>
              <GlassCard className="p-5" hoverLift={false}>
                <p className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">Source checks</p>
                <div className="mt-3 flex max-h-40 flex-wrap gap-2 overflow-y-auto pr-1">
                  {result.data_source_checks.map((check) => (
                    <StatusBadge key={`${check.source}-${check.checked_at}`} variant={sourceVariant(check.status)} className="max-w-full">
                      <span className="truncate">{check.source}</span>
                    </StatusBadge>
                  ))}
                </div>
                {result.degraded_reasons.length > 0 && (
                  <p className="mt-3 text-xs leading-relaxed text-(--color-accent-amber)">
                    {result.degraded_reasons.join(" ")}
                  </p>
                )}
              </GlassCard>
            </motion.div>
          )}

          <motion.div
            className="mb-6 flex flex-wrap gap-2"
            initial={reducedMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.35,
              delay: reducedMotion ? 0 : 0.1,
              ease: [0.25, 0.46, 0.45, 0.94],
            }}
          >
            <button
              type="button"
              onClick={() => setSelectedSector(ALL_SECTORS)}
              className={`rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${
                selectedSector === ALL_SECTORS
                  ? "border-(--color-accent-violet)/30 bg-(--color-accent-violet)/15 text-(--color-accent-violet)"
                  : "border-(--color-border-subtle) bg-(--color-surface-glass) text-(--color-text-secondary) hover:border-(--color-border-strong) hover:text-(--color-text-primary)"
              }`}
            >
              {ALL_SECTORS}
            </button>
            {sectors.map((sector) => {
              const active = selectedSector === sector;
              return (
                <button
                  key={sector}
                  type="button"
                  onClick={() => setSelectedSector(sector)}
                  className={`rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${
                    active
                      ? "border-(--color-accent-violet)/30 bg-(--color-accent-violet)/15 text-(--color-accent-violet)"
                      : "border-(--color-border-subtle) bg-(--color-surface-glass) text-(--color-text-secondary) hover:border-(--color-border-strong) hover:text-(--color-text-primary)"
                  }`}
                >
                  {sector}
                </button>
              );
            })}
          </motion.div>

          {filtered.length === 0 ? (
            <GlassCard className="p-6">
              <EmptyState
                title="No moonshots match this filter"
                description="Try selecting a different sector or refresh the list."
                icon={<Rocket className="h-6 w-6" />}
                action={{ label: "Clear filter", onClick: () => setSelectedSector(ALL_SECTORS) }}
              />
            </GlassCard>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((moonshot, index) => (
                <MoonshotCard key={moonshot.id} moonshot={moonshot} index={index} />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
