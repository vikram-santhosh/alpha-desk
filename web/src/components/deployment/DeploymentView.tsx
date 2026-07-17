import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  AlertTriangle,
  Clock3,
  Cpu,
  PieChart,
  Play,
  RefreshCw,
  Target,
  Wallet,
} from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { GlassButton } from "@/components/ui/GlassButton";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassInput } from "@/components/ui/GlassInput";
import { GlassSelect } from "@/components/ui/GlassSelect";
import { Markdown } from "@/components/ui/Markdown";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchLatestDeploymentPlan, streamDeploymentPlan } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { rise, stagger } from "@/lib/motion";
import type { DeploymentPlanResult } from "@/types";

const DEFAULT_THEMES = [
  "AI infrastructure / datacenter",
  "precious-metals miners",
  "defense / aerospace",
  "copper / critical minerals",
  "nuclear / uranium",
];

const DEFAULTS = {
  capital: "100000",
  returnTarget: "30-40% total return over 12 months",
  accountType: "taxable",
  constraints: "Reducing concentration is the #1 goal; concentrated single-stock positions are acceptable.",
  themes: DEFAULT_THEMES.join(", "),
};

const ACCOUNT_TYPES = ["taxable", "IRA", "401k"];

function statNumber(stats: Record<string, unknown>, key: string): number | null {
  const value = stats[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function StatTile({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof Clock3;
}) {
  return (
    <GlassCard className="p-4" hoverLift={false}>
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 text-(--color-accent-cyan)">
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <p className="text-xs text-(--color-text-tertiary)">{label}</p>
          <p className="truncate text-sm font-semibold text-(--color-text-primary)">{value}</p>
        </div>
      </div>
    </GlassCard>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-(--color-text-tertiary)">{label}</span>
      {children}
    </label>
  );
}

export default function DeploymentView() {
  const reduceMotion = useReducedMotion();
  const [plan, setPlan] = useState<DeploymentPlanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingMarkdown, setStreamingMarkdown] = useState("");
  const [progressMsg, setProgressMsg] = useState<string | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  const [capital, setCapital] = useState(DEFAULTS.capital);
  const [returnTarget, setReturnTarget] = useState(DEFAULTS.returnTarget);
  const [accountType, setAccountType] = useState(DEFAULTS.accountType);
  const [constraints, setConstraints] = useState(DEFAULTS.constraints);
  const [themes, setThemes] = useState(DEFAULTS.themes);

  // Pre-fill the form from the last run's mandate so re-runs reuse prior inputs.
  const hydrateForm = (mandate: Record<string, unknown>) => {
    if (typeof mandate.capital === "number") setCapital(String(mandate.capital));
    if (typeof mandate.return_target === "string") setReturnTarget(mandate.return_target);
    if (typeof mandate.account_type === "string") setAccountType(mandate.account_type);
    if (typeof mandate.constraints === "string") setConstraints(mandate.constraints);
    if (Array.isArray(mandate.tracked_themes)) setThemes(mandate.tracked_themes.join(", "));
  };

  const loadLatest = async () => {
    setLoading(true);
    setError(null);
    try {
      const latest = await fetchLatestDeploymentPlan();
      setPlan(latest);
      if (latest?.mandate) hydrateForm(latest.mandate);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load latest deployment plan");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLatest();
    return () => cancelRef.current?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRun = () => {
    const capitalValue = Number(capital.replace(/[^0-9.]/g, ""));
    if (!Number.isFinite(capitalValue) || capitalValue <= 0) {
      setError("Enter a capital amount greater than 0.");
      return;
    }
    cancelRef.current?.();
    setRunning(true);
    setError(null);
    setStreamingMarkdown("");
    setProgressMsg("Starting…");
    cancelRef.current = streamDeploymentPlan(
      {
        capital: capitalValue,
        return_target: returnTarget.trim() || undefined,
        account_type: accountType.trim() || undefined,
        constraints: constraints.trim() || undefined,
        themes: themes
          .split(",")
          .map((theme) => theme.trim())
          .filter(Boolean),
      },
      {
        onProgress: (message) => setProgressMsg(message),
        onChunk: (delta) => setStreamingMarkdown((prev) => prev + delta),
        onDone: (result) => {
          setPlan(result);
          setStreamingMarkdown("");
          setProgressMsg(null);
          setRunning(false);
          cancelRef.current = null;
        },
        onError: (message) => {
          setError(message);
          setStreamingMarkdown("");
          setProgressMsg(null);
          setRunning(false);
          cancelRef.current = null;
        },
      }
    );
  };

  const hhi = plan ? statNumber(plan.stats, "hhi") : null;
  const top1 = plan ? statNumber(plan.stats, "top1_pct") : null;
  const holdings = plan ? statNumber(plan.stats, "n_holdings") : null;
  const candidates = plan ? statNumber(plan.stats, "candidate_count") : null;

  const weightsBasis = plan && typeof plan.stats.weights_basis === "string" ? plan.stats.weights_basis : null;

  const concentrationValue = useMemo(() => {
    if (top1 === null && hhi === null) return "—";
    const parts: string[] = [];
    if (top1 !== null) parts.push(`top-1 ${top1.toFixed(0)}%`);
    if (hhi !== null) parts.push(`HHI ${hhi.toFixed(0)}`);
    const basis = weightsBasis === "market_value" ? " (mkt value)" : weightsBasis === "cost_basis" ? " (cost basis)" : "";
    return parts.join(" · ") + basis;
  }, [top1, hhi, weightsBasis]);

  return (
    <motion.div
      className="mx-auto max-w-7xl space-y-6"
      variants={stagger}
      initial={reduceMotion ? "visible" : "hidden"}
      animate="visible"
    >
      <motion.header
        variants={rise}
        className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between"
      >
        <div>
          <div className="flex items-center gap-2">
            <Target className="h-5 w-5 text-(--color-accent-cyan)" />
            <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">
              Deployment Plan
            </h1>
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-(--color-text-secondary)">
            Generate a decision-grade, add-only capital-deployment report grounded in your portfolio
            config, the deterministic score engine, live fundamentals, and a macro snapshot.
          </p>
        </div>
        <div className="flex gap-2">
          <GlassButton
            variant="ghost"
            onClick={loadLatest}
            disabled={running || loading}
            leftIcon={<RefreshCw className="h-4 w-4" />}
          >
            Refresh
          </GlassButton>
          <GlassButton
            onClick={handleRun}
            disabled={running}
            leftIcon={
              running ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />
            }
          >
            {running ? "Generating" : "Generate plan"}
          </GlassButton>
        </div>
      </motion.header>

      <motion.div variants={rise}>
        <GlassCard className="p-5" hoverLift={false}>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <Field label="Capital to deploy ($)">
              <GlassInput
                inputMode="numeric"
                value={capital}
                onChange={(event) => setCapital(event.target.value)}
                disabled={running}
                placeholder="100000"
              />
            </Field>
            <Field label="Return target">
              <GlassInput
                value={returnTarget}
                onChange={(event) => setReturnTarget(event.target.value)}
                disabled={running}
              />
            </Field>
            <Field label="Account type">
              <GlassSelect
                value={accountType}
                onChange={(event) => setAccountType(event.target.value)}
                disabled={running}
              >
                {ACCOUNT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </GlassSelect>
            </Field>
            <Field label="Tracked themes (comma-separated)">
              <GlassInput
                value={themes}
                onChange={(event) => setThemes(event.target.value)}
                disabled={running}
              />
            </Field>
            <div className="md:col-span-2">
              <Field label="Risk constraints">
                <GlassInput
                  value={constraints}
                  onChange={(event) => setConstraints(event.target.value)}
                  disabled={running}
                />
              </Field>
            </div>
          </div>
        </GlassCard>
      </motion.div>

      {error && (
        <motion.div variants={rise}>
          <GlassCard className="p-4" glow="rose" hoverLift={false}>
            <div className="flex items-start gap-3 text-(--color-accent-rose)">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <p className="text-sm text-(--color-text-primary)">{error}</p>
            </div>
          </GlassCard>
        </motion.div>
      )}

      {loading ? (
        <motion.div variants={rise} className="space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
          <Skeleton className="h-[520px]" />
        </motion.div>
      ) : running ? (
        <motion.div variants={rise}>
          <GlassCard className="overflow-hidden" hoverLift={false}>
            <div className="flex items-center gap-3 border-b border-(--color-border-subtle) px-5 py-4">
              <RefreshCw className="h-4 w-4 animate-spin text-(--color-accent-cyan)" />
              <div>
                <h2 className="text-lg font-semibold text-(--color-text-primary)">Generating deployment plan…</h2>
                <p className="text-xs text-(--color-text-tertiary)">{progressMsg ?? "Working…"}</p>
              </div>
            </div>
            <article className="px-5 py-7 sm:px-8">
              {streamingMarkdown ? (
                <div className="mx-auto max-w-3xl">
                  <Markdown>{streamingMarkdown}</Markdown>
                </div>
              ) : (
                <div className="mx-auto max-w-3xl space-y-3">
                  <Skeleton className="h-5 w-2/3" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-5/6" />
                </div>
              )}
            </article>
          </GlassCard>
        </motion.div>
      ) : plan ? (
        <>
          <motion.div variants={rise} className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Generated"
              value={plan.saved_at ? formatDateTime(plan.saved_at) : formatDateTime(plan.generated_at)}
              icon={Clock3}
            />
            <StatTile
              label="Synthesis model"
              value={plan.cost_usd > 0 ? `${plan.model} · $${plan.cost_usd.toFixed(4)}` : plan.model}
              icon={Cpu}
            />
            <StatTile label="Concentration" value={concentrationValue} icon={PieChart} />
            <StatTile
              label="Coverage"
              value={`${holdings ?? 0} holdings · ${candidates ?? 0} candidates`}
              icon={Wallet}
            />
          </motion.div>

          {plan.degraded_reasons.length > 0 && (
            <motion.div variants={rise}>
              <GlassCard className="p-4" glow="amber" hoverLift={false}>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h2 className="text-sm font-semibold text-(--color-text-primary)">
                    Data caveats
                  </h2>
                  <StatusBadge variant="warning">{plan.degraded_reasons.length}</StatusBadge>
                </div>
                <ul className="space-y-2 text-sm text-(--color-text-secondary)">
                  {plan.degraded_reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </GlassCard>
            </motion.div>
          )}

          <motion.div variants={rise}>
            <GlassCard className="overflow-hidden" hoverLift={false}>
              <div className="flex flex-col gap-2 border-b border-(--color-border-subtle) px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-(--color-text-primary)">
                    Capital-deployment report
                  </h2>
                  <p className="text-xs text-(--color-text-tertiary)">
                    {plan.run_id ? `Run #${plan.run_id}` : "Not persisted"}
                  </p>
                </div>
                <StatusBadge variant={plan.saved_at ? "success" : "warning"}>
                  {plan.saved_at ? "Saved" : "Unsaved"}
                </StatusBadge>
              </div>
              <article className="px-5 py-7 sm:px-8">
                {plan.markdown ? (
                  <div className="mx-auto max-w-3xl">
                    <Markdown>{plan.markdown}</Markdown>
                  </div>
                ) : (
                  <p className="text-sm text-(--color-text-tertiary)">
                    The synthesis call returned no report text.
                  </p>
                )}
              </article>
            </GlassCard>
          </motion.div>
        </>
      ) : (
        <motion.div variants={rise}>
          <GlassCard hoverLift={false}>
            <EmptyState
              icon={<Target className="h-6 w-6" />}
              title="No deployment plan yet"
              description="Set your capital and constraints above, then generate the first plan."
              action={{ label: "Generate plan", onClick: handleRun }}
            />
          </GlassCard>
        </motion.div>
      )}
    </motion.div>
  );
}
