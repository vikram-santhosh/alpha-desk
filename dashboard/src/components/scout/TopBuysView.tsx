import type { TopBuysResult } from "@/types";
import { useCallback, useEffect, useState } from "react";
import { motion } from "motion/react";
import { fetchTopBuys, runScoreEngine } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassButton } from "@/components/ui/GlassButton";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ScoreCard } from "./ScoreCard";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { BarChart3, RefreshCw, Zap } from "lucide-react";

function DiagnosticPill({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/50 px-4 py-2.5 text-center">
      <span className={`font-mono text-xl font-bold tabular-nums ${accent ? "text-(--color-accent-cyan)" : "text-(--color-text-primary)"}`}>
        {value}
      </span>
      <span className="mt-0.5 text-[10px] uppercase tracking-wider text-(--color-text-tertiary)">{label}</span>
    </div>
  );
}

export default function TopBuysView() {
  const [result, setResult]     = useState<TopBuysResult | null>(null);
  const [hydrating, setHydrating] = useState(true);
  const [running, setRunning]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const reducedMotion = useReducedMotion();

  // On mount: load the latest snapshot (cheap, no LLM)
  useEffect(() => {
    let active = true;
    fetchTopBuys()
      .then(data => { if (active) setResult(data); })
      .catch(err  => { if (active) setError(err instanceof Error ? err.message : "Failed to load scores"); })
      .finally(()  => { if (active) setHydrating(false); });
    return () => { active = false; };
  }, []);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const data = await runScoreEngine();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Score engine failed");
    } finally {
      setRunning(false);
    }
  }, []);

  const handleRefresh = useCallback(async () => {
    setError(null);
    try {
      const data = await fetchTopBuys();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh");
    }
  }, []);

  const isMock = result?.source === "mock";

  return (
    <section className="mx-auto max-w-7xl space-y-6">
      {/* Header */}
      <motion.header
        className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between"
        initial={reducedMotion ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.25, 0.46, 0.45, 0.94] }}
      >
        <div>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-(--color-accent-cyan)" aria-hidden="true" />
            <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">
              Top Buys
            </h1>
            {isMock && (
              <StatusBadge variant="warning">mock data</StatusBadge>
            )}
            {result && !isMock && (
              <StatusBadge variant="success">live</StatusBadge>
            )}
          </div>
          <p className="mt-1 text-sm text-(--color-text-secondary)">
            Multi-platform conviction scores — breadth-gated, deterministic, 0–10.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <GlassButton
            variant="ghost"
            leftIcon={<RefreshCw className="h-4 w-4" />}
            onClick={() => void handleRefresh()}
            disabled={hydrating || running}
          >
            Refresh
          </GlassButton>
          <GlassButton
            variant="solid"
            leftIcon={<Zap className={`h-4 w-4 ${running ? "animate-pulse" : ""}`} />}
            onClick={() => void handleRun()}
            disabled={running}
          >
            {running ? "Running…" : "Run score engine"}
          </GlassButton>
        </div>
      </motion.header>

      {/* Loading skeleton */}
      {hydrating && !result && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Skeleton className="h-72" />
            <Skeleton className="h-72" />
            <Skeleton className="h-72" />
          </div>
        </div>
      )}

      {/* Error */}
      {error && !result && (
        <GlassCard glow="rose" className="p-6">
          <EmptyState
            title="Score engine unavailable"
            description={error}
            icon={<BarChart3 className="h-6 w-6" />}
            action={{ label: "Run score engine", onClick: () => void handleRun() }}
          />
        </GlassCard>
      )}

      {/* Content */}
      {result && (
        <>
          {/* Diagnostics bar */}
          <motion.div
            initial={reducedMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: reducedMotion ? 0 : 0.05 }}
            className="space-y-3"
          >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <DiagnosticPill label="tickers scored" value={result.diagnostics.tickers_scored} accent />
              <DiagnosticPill label="signals"        value={result.diagnostics.signals_collected} />
              <DiagnosticPill label="elapsed"        value={`${result.diagnostics.elapsed_s}s`} />
              <DiagnosticPill label="platforms ok"   value={result.diagnostics.sensors_ok.length} accent />
            </div>

            <GlassCard className="p-4" hoverLift={false}>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-(--color-text-tertiary)">Snapshot</p>
                  <p className="font-mono text-xs text-(--color-text-secondary)">{result.snapshot_id}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-(--color-text-tertiary)">Weights</p>
                  <p className="font-mono text-xs text-(--color-text-secondary)">{result.weights_version}</p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {result.diagnostics.sensors_ok.map(s => (
                    <StatusBadge key={s} variant="success">{s}</StatusBadge>
                  ))}
                  {result.diagnostics.sensors_failed.map(s => (
                    <StatusBadge key={s} variant="critical">{s}</StatusBadge>
                  ))}
                </div>
                {isMock && (
                  <p className="ml-auto text-xs text-(--color-accent-amber)">
                    Backend offline — showing mock data. Run the score engine server to get live scores.
                  </p>
                )}
              </div>
            </GlassCard>
          </motion.div>

          {/* Score cards */}
          {result.top.length === 0 ? (
            <GlassCard className="p-8" hoverLift={false}>
              <EmptyState
                title="No scores yet"
                description="Run the score engine to generate ranked buy recommendations."
                icon={<BarChart3 className="h-6 w-6" />}
                action={{ label: "Run score engine", onClick: () => void handleRun() }}
              />
            </GlassCard>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {result.top.map((entry, i) => (
                <ScoreCard key={entry.ticker} entry={entry} rank={i + 1} index={i} />
              ))}
            </div>
          )}

          {/* Breadth-gate legend */}
          <motion.div
            initial={reducedMotion ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: reducedMotion ? 0 : 0.4 }}
          >
            <GlassCard className="p-4" hoverLift={false}>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-tertiary)">
                Breadth gate — how scores are capped
              </p>
              <div className="mt-3 flex flex-wrap gap-4 text-xs text-(--color-text-secondary)">
                <span><span className="text-(--color-accent-violet) font-medium">8–10 Top tier</span> — 3+ platforms agreeing</span>
                <span><span className="text-(--color-accent-cyan) font-medium">7–7.9 Confirmed</span> — 2+ platforms agreeing</span>
                <span><span className="text-(--color-accent-amber) font-medium">0–6.9 Weak</span> — single-platform signal</span>
                <span><span className="text-(--color-accent-rose) font-medium">Bear</span> — net negative across platforms</span>
              </div>
            </GlassCard>
          </motion.div>
        </>
      )}
    </section>
  );
}
