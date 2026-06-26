import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { BrainCircuit, Loader2, Play, RotateCcw } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { fetchCouncilModels } from "@/lib/api";
import { useCouncilStream } from "@/lib/useCouncilStream";
import { rise, stagger } from "@/lib/motion";
import { cn } from "@/lib/cn";
import type { CouncilEvent, JudgeAnalysis, ModelOption, PanelVerdict, Rating, Verdict } from "@/types";
import { GlassButton } from "@/components/ui/GlassButton";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassInput } from "@/components/ui/GlassInput";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";

const fallbackRoster: ModelOption[] = [
  { model_id: "z-ai/glm-5.2", label: "GLM 5.2", provider: "z-ai", enabled: true },
  { model_id: "moonshotai/kimi-k2.6", label: "Kimi K2.6", provider: "moonshotai", enabled: true },
  { model_id: "deepseek/deepseek-v4-pro", label: "DeepSeek V4 Pro", provider: "deepseek", enabled: true },
];

const ratingVariant: Record<Rating, "info" | "success" | "warning" | "critical" | "neutral"> = {
  Buy: "success",
  Overweight: "info",
  Hold: "neutral",
  Underweight: "warning",
  Sell: "critical",
};

function reduceEvents(events: CouncilEvent[]) {
  return events.reduce(
    (state, event) => {
      if (event.type === "panel_started") return { ...state, ticker: event.data.ticker, models: event.data.models };
      if (event.type === "panel_model_result") return { ...state, panel: [...state.panel.filter((item) => item.model_id !== event.data.model_id), event.data] };
      if (event.type === "judge_result") return { ...state, judge: event.data };
      if (event.type === "verdict") return { ...state, verdict: event.data };
      if (event.type === "error") return { ...state, error: event.data.message };
      return state;
    },
    { models: [] as string[], panel: [] as PanelVerdict[], judge: undefined as JudgeAnalysis | undefined, verdict: undefined as Verdict | undefined, ticker: undefined as string | undefined, error: undefined as string | undefined }
  );
}

function modelDisplayName(modelId: string) {
  return modelId.split("/").at(-1)?.replaceAll("-", " ") ?? modelId;
}

function formatElapsed(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return minutes > 0 ? `${minutes}m ${remaining.toString().padStart(2, "0")}s` : `${remaining}s`;
}

function councilContextFromParams(searchParams: URLSearchParams) {
  const source = searchParams.get("source") || searchParams.get("from") || undefined;
  const ideaRunId = Number(searchParams.get("idea_run_id") || "");
  const scoreSnapshotId = searchParams.get("score_snapshot_id") || undefined;
  return {
    source,
    idea_run_id: Number.isFinite(ideaRunId) && ideaRunId > 0 ? ideaRunId : undefined,
    score_snapshot_id: scoreSnapshotId,
  };
}

function RunningCouncilBanner({
  activeRun,
  completedCount,
  completedIds,
  displayedModels,
  elapsedSeconds,
}: {
  activeRun?: { ticker: string; models: string[] };
  completedCount: number;
  completedIds: string[];
  displayedModels: string[];
  elapsedSeconds: number;
}) {
  const total = Math.max(1, displayedModels.length || activeRun?.models.length || 1);
  const pct = Math.max(8, Math.min(96, Math.round((completedCount / total) * 100)));
  return (
    <GlassCard className="border-(--color-accent-cyan)/35 p-4" glow="cyan" hoverLift={false}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3">
          <Loader2 className="mt-0.5 h-5 w-5 animate-spin text-(--color-accent-cyan)" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold text-(--color-text-primary)">
              Live council running{activeRun?.ticker ? ` for ${activeRun.ticker}` : ""}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-(--color-text-secondary)">
              Calling OpenRouter seats sequentially, then running cross-examination. Elapsed {formatElapsed(elapsedSeconds)}.
            </p>
          </div>
        </div>
        <div className="min-w-44">
          <div className="flex items-center justify-between text-xs text-(--color-text-tertiary)">
            <span>{completedCount}/{total} seats returned</span>
            <span className="font-mono">{formatElapsed(elapsedSeconds)}</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-(--color-surface-elevated)">
            <div className="h-full rounded-full bg-(--color-accent-cyan) transition-[width] duration-700" style={{ width: `${pct}%` }} />
          </div>
        </div>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {displayedModels.map((modelId) => {
          const complete = completedIds.includes(modelId);
          return (
            <div key={modelId} className="flex items-center justify-between gap-2 rounded-lg border border-(--color-border-subtle) bg-(--color-surface-elevated)/35 px-3 py-2">
              <span className="truncate text-xs text-(--color-text-secondary)">{modelDisplayName(modelId)}</span>
              <StatusBadge variant={complete ? "success" : "info"}>{complete ? "returned" : "pending"}</StatusBadge>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}

function ClaimList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <p className="text-[0.65rem] font-medium uppercase tracking-wider text-(--color-text-tertiary)">{title}</p>
      <ul className="mt-1 space-y-1">
        {items.slice(0, 3).map((item) => (
          <li key={item} className="rounded-lg border border-(--color-border-subtle) bg-(--color-surface-elevated)/35 px-2.5 py-1.5 text-xs leading-relaxed text-(--color-text-secondary)">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function PanelCard({ modelId, verdict }: { modelId: string; verdict?: PanelVerdict }) {
  return (
    <GlassCard className={cn("p-4", verdict?.dissent && "border-(--color-accent-violet)/40")} hoverLift={false}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-(--color-text-primary)">
            {verdict?.label ?? modelDisplayName(modelId)}
          </h3>
          <p className="mt-1 truncate font-mono text-xs text-(--color-text-tertiary)">
            {verdict?.model_id ?? modelId}
          </p>
        </div>
        {verdict?.dissent ? <StatusBadge variant="info">Dissent</StatusBadge> : null}
      </div>

      {verdict ? (
        <div className="mt-4 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <StatusBadge variant={ratingVariant[verdict.rating]}>{verdict.rating}</StatusBadge>
            <span className="font-mono text-xs text-(--color-text-secondary)">
              {Math.round(verdict.confidence * 100)}%
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-(--color-surface-elevated)">
            <div
              className="h-full rounded-full bg-(--color-accent-cyan)"
              style={{ width: `${Math.max(0, Math.min(verdict.confidence, 1)) * 100}%` }}
            />
          </div>
          <p className="text-sm leading-relaxed text-(--color-text-secondary)">{verdict.thesis}</p>
          <div className="grid gap-3">
            <ClaimList title="Accepts" items={verdict.accepted_claims} />
            <ClaimList title="Rejects" items={verdict.rejected_claims} />
            <ClaimList title="Challenges" items={verdict.challenges} />
          </div>
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <Skeleton className="h-6 w-28" />
          <Skeleton className="h-2 w-full" />
          <Skeleton className="h-2 w-4/5" />
        </div>
      )}
    </GlassCard>
  );
}

function JudgeCard({ judge }: { judge?: JudgeAnalysis }) {
  return (
    <GlassCard className="p-5" glow="cyan" hoverLift={false}>
      <p className="text-xs font-semibold uppercase tracking-wider text-(--color-text-tertiary)">Council judge</p>
      <h3 className="mt-2 text-lg font-semibold text-(--color-text-primary)">Synthesis</h3>
      <div className="mt-4 grid gap-4">
        {[
          ["Consensus", judge?.consensus ?? []],
          ["Contradictions", judge?.contradictions ?? []],
          ["Blind spots", judge?.blind_spots ?? []],
        ].map(([title, items]) => (
          <div key={title as string}>
            <p className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">{title as string}</p>
            <ul className="mt-2 space-y-2">
              {(items as string[]).length ? (items as string[]).map((item) => (
                <li key={item} className="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/40 px-3 py-2 text-sm text-(--color-text-secondary)">
                  {item}
                </li>
              )) : (
                <li className="text-sm text-(--color-text-tertiary)">Waiting for judge output.</li>
              )}
            </ul>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

function VerdictCard({ verdict }: { verdict?: Verdict }) {
  return (
    <GlassCard className="p-5" glow={verdict ? "amber" : false} hoverLift={false}>
      <p className="text-xs font-semibold uppercase tracking-wider text-(--color-text-tertiary)">Final verdict</p>
      {verdict ? (
        <div className="mt-3 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-xl font-semibold text-(--color-text-primary)">{verdict.ticker} {verdict.conviction_label}</h3>
            <StatusBadge variant={ratingVariant[verdict.rating]}>{verdict.rating}</StatusBadge>
          </div>
          <div>
            <div className="flex items-center justify-between text-xs text-(--color-text-secondary)">
              <span>Conviction</span>
              <span className="font-mono">{Math.round(verdict.conviction * 100)}%</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-(--color-surface-elevated)">
              <div className="h-full rounded-full bg-(--color-accent-amber)" style={{ width: `${verdict.conviction * 100}%` }} />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">Catalysts</p>
              <ul className="mt-2 space-y-2 text-sm text-(--color-text-secondary)">
                {verdict.catalysts.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">Risks</p>
              <ul className="mt-2 space-y-2 text-sm text-(--color-text-secondary)">
                {verdict.risks.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          </div>
        </div>
      ) : (
        <p className="mt-3 text-sm text-(--color-text-secondary)">Run the backend council to stream a verdict here.</p>
      )}
    </GlassCard>
  );
}

export default function CouncilView() {
  const reduceMotion = useReducedMotion();
  const [searchParams] = useSearchParams();
  const stream = useCouncilStream();
  const state = reduceEvents(stream.events);
  const initialTicker = searchParams.get("ticker")?.trim().toUpperCase() || "NVDA";
  const [ticker, setTicker] = useState(initialTicker);
  const [models, setModels] = useState<ModelOption[]>(fallbackRoster);
  const [enabledById, setEnabledById] = useState<Record<string, boolean>>(
    Object.fromEntries(fallbackRoster.map((model) => [model.model_id, model.enabled]))
  );
  const [modelsError, setModelsError] = useState<string | null>(null);
  const autoRunKeyRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchCouncilModels()
      .then((nextModels) => {
        if (cancelled || nextModels.length === 0) return;
        setModels(nextModels);
        setEnabledById(Object.fromEntries(nextModels.map((model) => [model.model_id, model.enabled])));
      })
      .catch((error) => {
        if (!cancelled) setModelsError(error instanceof Error ? error.message : "Failed to load council models");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedModels = useMemo(
    () => models.filter((model) => enabledById[model.model_id]).map((model) => model.model_id),
    [enabledById, models]
  );
  const displayedModels = state.models.length ? state.models : selectedModels;
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const councilContext = useMemo(() => councilContextFromParams(searchParams), [searchParams]);
  const contextLabel = useMemo(() => {
    if (councilContext.source === "scout") {
      return `Using Alpha Scout context${councilContext.idea_run_id ? ` from run #${councilContext.idea_run_id}` : ""}.`;
    }
    if (councilContext.source === "score_engine") {
      return `Using score-engine context${councilContext.score_snapshot_id ? ` from ${councilContext.score_snapshot_id}` : ""}.`;
    }
    return "";
  }, [councilContext]);

  useEffect(() => {
    const queryTicker = searchParams.get("ticker")?.trim().toUpperCase();
    if (queryTicker) setTicker(queryTicker);
  }, [searchParams]);

  useEffect(() => {
    const queryTicker = searchParams.get("ticker")?.trim().toUpperCase();
    const shouldRun = searchParams.get("run") === "1" || searchParams.get("autorun") === "1";
    if (!queryTicker || !shouldRun || selectedModels.length === 0 || stream.status === "loading") return;
    const runKey = JSON.stringify([queryTicker, councilContext]);
    if (autoRunKeyRef.current === runKey) return;
    autoRunKeyRef.current = runKey;
    stream.runCouncil({ ticker: queryTicker, models: selectedModels, ...councilContext });
  }, [councilContext, searchParams, selectedModels, stream]);

  useEffect(() => {
    if (stream.status !== "loading") {
      setElapsedSeconds(0);
      return undefined;
    }
    setElapsedSeconds(0);
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.max(1, Math.floor((Date.now() - startedAt) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [stream.status, stream.activeRun]);

  const run = () => {
    const cleaned = ticker.trim().toUpperCase();
    if (!cleaned || selectedModels.length === 0) return;
    stream.runCouncil({ ticker: cleaned, models: selectedModels, ...councilContext });
  };

  return (
    <motion.div
      className="mx-auto max-w-7xl space-y-6"
      variants={stagger}
      initial={reduceMotion ? "visible" : "hidden"}
      animate="visible"
    >
      <motion.header variants={rise} className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-(--color-accent-cyan)" />
            <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">Model Council</h1>
          </div>
          <p className="mt-1 text-sm text-(--color-text-secondary)">
            Streams `/api/council/stream` from the FastAPI backend with Scout or score context when available.
          </p>
          {contextLabel && (
            <p className="mt-1 font-mono text-xs text-(--color-accent-cyan)">
              {contextLabel}
            </p>
          )}
        </div>
        <StatusBadge variant={stream.status === "loading" ? "info" : stream.status === "error" ? "critical" : "success"}>
          {stream.status === "idle" ? "Ready" : stream.status}
        </StatusBadge>
      </motion.header>

      <motion.div variants={rise}>
        <GlassCard className="p-5" glow="cyan" hoverLift={false}>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div>
              <label className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)" htmlFor="council-ticker">
                Ticker or idea
              </label>
              <GlassInput
                id="council-ticker"
                className="mt-2"
                value={ticker}
                onChange={(event) => setTicker(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") run();
                }}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <GlassButton leftIcon={<Play className="h-4 w-4" />} onClick={run} disabled={stream.status === "loading" || selectedModels.length === 0}>
                Run council
              </GlassButton>
              {stream.status === "error" && (
                <GlassButton variant="ghost" leftIcon={<RotateCcw className="h-4 w-4" />} onClick={stream.retry}>
                  Retry
                </GlassButton>
              )}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {models.map((model) => {
              const enabled = Boolean(enabledById[model.model_id]);
              return (
                <button
                  key={model.model_id}
                  type="button"
                  aria-pressed={enabled}
                  onClick={() => setEnabledById((current) => ({ ...current, [model.model_id]: !current[model.model_id] }))}
                  className={cn(
                    "rounded-full border px-3 py-2 text-left text-xs transition",
                    enabled
                      ? "border-(--color-accent-cyan)/40 bg-(--color-accent-cyan)/10 text-(--color-text-primary)"
                      : "border-(--color-border-subtle) bg-(--color-surface-glass) text-(--color-text-tertiary)"
                  )}
                >
                  <span className="font-medium">{model.label}</span>
                  <span className="ml-2 font-mono opacity-70">{model.provider}</span>
                </button>
              );
            })}
          </div>
          {modelsError && (
            <p className="mt-3 text-xs text-(--color-accent-amber)">
              Model roster fallback in use: {modelsError}
            </p>
          )}
        </GlassCard>
      </motion.div>

      {stream.error && (
        <GlassCard className="p-4" glow="rose" hoverLift={false}>
          <p className="text-sm text-(--color-text-primary)">{stream.error}</p>
        </GlassCard>
      )}

      {stream.status === "loading" && (
        <motion.div variants={rise}>
          <RunningCouncilBanner
            activeRun={stream.activeRun}
            completedCount={state.panel.length}
            completedIds={state.panel.map((item) => item.model_id)}
            displayedModels={displayedModels}
            elapsedSeconds={elapsedSeconds}
          />
        </motion.div>
      )}

      <motion.div variants={rise} className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.6fr)]">
        <div className="grid gap-4 md:grid-cols-2">
          {displayedModels.map((modelId) => (
            <PanelCard key={modelId} modelId={modelId} verdict={state.panel.find((item) => item.model_id === modelId)} />
          ))}
        </div>
        <div className="space-y-4">
          <JudgeCard judge={state.judge} />
          <VerdictCard verdict={state.verdict} />
          {stream.done && (
            <GlassCard className="p-4" hoverLift={false}>
              <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                <span className="text-(--color-text-secondary)">Mode: {stream.done.council_mode}</span>
                <span className="font-mono text-(--color-accent-emerald)">${stream.done.cost_usd.toFixed(4)}</span>
              </div>
              {stream.done.run_id && (
                <p className="mt-2 text-xs text-(--color-text-tertiary)">
                  saved run #{stream.done.run_id}{stream.done.saved_at ? ` · ${new Date(stream.done.saved_at).toLocaleString()}` : ""}
                </p>
              )}
              {stream.done.degraded_reasons.length > 0 && (
                <p className="mt-2 text-xs text-(--color-accent-amber)">
                  {stream.done.degraded_reasons.join(" ")}
                </p>
              )}
            </GlassCard>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
