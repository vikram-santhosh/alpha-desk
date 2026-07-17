import { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  AlertTriangle,
  Clock3,
  FileText,
  Play,
  RefreshCw,
  WalletCards,
} from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { GlassButton } from "@/components/ui/GlassButton";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassSelect } from "@/components/ui/GlassSelect";
import { Markdown } from "@/components/ui/Markdown";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchLatestBrief, runBrief } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { rise, stagger } from "@/lib/motion";
import type { BriefRunResult, BriefRunType } from "@/types";

const RUN_LABELS: Record<BriefRunType, string> = {
  morning_full: "Morning full",
  evening_wrap: "Evening wrap",
  weekend: "Weekend",
  auto: "Auto",
};

// The brief arrives as a Telegram-style blob (HTML tags + markdown bold + box-
// drawing rules + emoji). Normalize it into clean markdown so the shared
// <Markdown> renderer gives it real headings, dividers, lists, and tables.
function normalizeBrief(value: string) {
  const text = value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .trim();

  return text
    .split("\n")
    .map((line) => {
      const t = line.trim();
      // Box-drawing / dash separator → markdown horizontal rule.
      if (/^[═━─–—_-]{4,}$/.test(t)) return "---";
      // A line that is entirely bold → section heading.
      const bold = t.match(/^\*\*(.+?)\*\*:?$/);
      if (bold) return `## ${bold[1].trim()}`;
      return line;
    })
    .join("\n");
}

function statNumber(stats: Record<string, unknown>, key: string) {
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

export default function BriefView() {
  const reduceMotion = useReducedMotion();
  const [runType, setRunType] = useState<BriefRunType>("morning_full");
  const [brief, setBrief] = useState<BriefRunResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const renderedBrief = useMemo(() => normalizeBrief(brief?.formatted ?? ""), [brief]);
  const totalTime = brief ? statNumber(brief.stats, "total_time_s") : null;
  const runCost = brief ? statNumber(brief.stats, "run_cost") : null;
  const holdingsCount = brief ? statNumber(brief.stats, "holdings_count") : null;

  const loadLatest = async () => {
    setLoading(true);
    setError(null);
    try {
      setBrief(await fetchLatestBrief());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load latest brief");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLatest();
  }, []);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    try {
      setBrief(await runBrief(runType));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Brief run failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <motion.div
      className="mx-auto max-w-7xl space-y-6"
      variants={stagger}
      initial={reduceMotion ? "visible" : "hidden"}
      animate="visible"
    >
      <motion.header variants={rise} className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-(--color-accent-cyan)" />
            <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">Daily Brief</h1>
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-(--color-text-secondary)">
            Run the AlphaDesk advisor pipeline and review the latest saved brief from the web cockpit.
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <GlassSelect
            label="Run type"
            value={runType}
            onChange={(event) => setRunType(event.target.value as BriefRunType)}
            disabled={running}
            className="min-w-48"
          >
            {Object.entries(RUN_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </GlassSelect>
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
              leftIcon={running ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            >
              {running ? "Running" : "Run"}
            </GlassButton>
          </div>
        </div>
      </motion.header>

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
          <div className="grid gap-4 md:grid-cols-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
          <Skeleton className="h-[520px]" />
        </motion.div>
      ) : brief ? (
        <>
          <motion.div variants={rise} className="grid gap-4 md:grid-cols-3">
            <StatTile
              label="Saved"
              value={brief.saved_at ? formatDateTime(brief.saved_at) : "Unsaved"}
              icon={Clock3}
            />
            <StatTile
              label="Cost"
              value={runCost === null ? "Unknown" : `$${runCost.toFixed(4)}`}
              icon={WalletCards}
            />
            <StatTile
              label="Coverage"
              value={holdingsCount === null ? brief.run_type : `${holdingsCount} holdings`}
              icon={FileText}
            />
          </motion.div>

          {brief.degraded_reasons.length > 0 && (
            <motion.div variants={rise}>
              <GlassCard className="p-4" glow="amber" hoverLift={false}>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h2 className="text-sm font-semibold text-(--color-text-primary)">Degraded reasons</h2>
                  <StatusBadge variant="warning">{brief.degraded_reasons.length}</StatusBadge>
                </div>
                <ul className="space-y-2 text-sm text-(--color-text-secondary)">
                  {brief.degraded_reasons.map((reason) => (
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
                    {RUN_LABELS[(brief.run_type as BriefRunType) || "morning_full"] ?? brief.run_type}
                  </h2>
                  <p className="text-xs text-(--color-text-tertiary)">
                    {brief.run_id ? `Run #${brief.run_id}` : "Not persisted"}
                    {totalTime !== null ? ` · ${totalTime.toFixed(1)}s` : ""}
                  </p>
                </div>
                <StatusBadge variant={brief.saved_at ? "success" : "warning"}>
                  {brief.saved_at ? "Saved" : "Unsaved"}
                </StatusBadge>
              </div>
              <article className="px-5 py-7 sm:px-8">
                {renderedBrief ? (
                  <div className="mx-auto max-w-3xl">
                    <Markdown>{renderedBrief}</Markdown>
                  </div>
                ) : (
                  <p className="text-sm text-(--color-text-tertiary)">Brief run returned no formatted text.</p>
                )}
              </article>
            </GlassCard>
          </motion.div>
        </>
      ) : (
        <motion.div variants={rise}>
          <GlassCard hoverLift={false}>
            <EmptyState
              icon={<FileText className="h-6 w-6" />}
              title="No saved brief"
              description="Run the advisor pipeline to create the first web brief."
              action={{ label: "Run brief", onClick: handleRun }}
            />
          </GlassCard>
        </motion.div>
      )}
    </motion.div>
  );
}
