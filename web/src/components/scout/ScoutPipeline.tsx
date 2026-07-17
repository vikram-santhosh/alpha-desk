import { motion } from "motion/react";
import { Check, CircleDashed, Loader2, Minus, X } from "lucide-react";
import type { ScoutProgress, ScoutStage, ScoutStageStatus } from "@/types";
import { GlassCard } from "@/components/ui/GlassCard";

function StageIcon({ status }: { status: ScoutStageStatus }) {
  switch (status) {
    case "running":
      return <Loader2 className="h-4 w-4 animate-spin text-(--color-accent-cyan)" />;
    case "done":
      return <Check className="h-4 w-4 text-(--color-accent-emerald)" />;
    case "error":
      return <X className="h-4 w-4 text-(--color-accent-rose)" />;
    case "skipped":
      return <Minus className="h-4 w-4 text-(--color-text-tertiary)" />;
    default:
      return <CircleDashed className="h-4 w-4 text-(--color-text-tertiary)" />;
  }
}

function StageRow({ stage, index, total }: { stage: ScoutStage; index: number; total: number }) {
  const active = stage.status === "running";
  return (
    <div className="flex items-start gap-3">
      <div className="flex flex-col items-center">
        <div
          className={`flex h-7 w-7 items-center justify-center rounded-full border transition-colors ${
            active
              ? "border-(--color-accent-cyan) bg-(--color-accent-cyan)/10"
              : stage.status === "done"
                ? "border-(--color-accent-emerald)/40 bg-(--color-accent-emerald)/10"
                : "border-(--color-border-subtle) bg-(--color-surface-glass)"
          }`}
        >
          <StageIcon status={stage.status} />
        </div>
        {index < total - 1 && (
          <div
            className={`my-0.5 w-px flex-1 ${
              stage.status === "done" ? "bg-(--color-accent-emerald)/40" : "bg-(--color-border-subtle)"
            }`}
            style={{ minHeight: 14 }}
          />
        )}
      </div>
      <div className="pb-3">
        <div
          className={`text-sm font-medium ${
            active ? "text-(--color-text-primary)" : stage.status === "done" ? "text-(--color-text-secondary)" : "text-(--color-text-tertiary)"
          }`}
        >
          {stage.label}
        </div>
        {stage.detail && active && (
          <div className="mt-0.5 text-xs text-(--color-text-tertiary)">{stage.detail}</div>
        )}
      </div>
    </div>
  );
}

export function ScoutPipeline({ progress }: { progress: ScoutProgress | null }) {
  if (!progress || progress.stages.length === 0) return null;
  const done = progress.stages.filter((s) => s.status === "done").length;
  const pct = Math.round((done / progress.stages.length) * 100);

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <GlassCard className="p-5" hoverLift={false} glow={progress.error ? "rose" : progress.active ? "cyan" : false}>
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-(--color-text-primary)">Alpha Scout pipeline</span>
            {progress.mode && (
              <span className="rounded-full bg-(--color-surface-glass) px-2 py-0.5 text-[11px] text-(--color-text-secondary)">
                {progress.mode}
              </span>
            )}
          </div>
          <span className="text-xs tabular-nums text-(--color-text-tertiary)">
            {progress.error ? "failed" : progress.active ? `${pct}%` : "complete"}
          </span>
        </div>

        <div className="mb-4 h-1 overflow-hidden rounded-full bg-(--color-surface-glass)">
          <motion.div
            className={`h-full ${progress.error ? "bg-(--color-accent-rose)" : "bg-(--color-accent-cyan)"}`}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.4 }}
          />
        </div>

        <div>
          {progress.stages.map((stage, i) => (
            <StageRow key={stage.key} stage={stage} index={i} total={progress.stages.length} />
          ))}
        </div>

        {progress.error && (
          <div className="mt-1 text-xs text-(--color-accent-rose)">Pipeline error: {progress.error}</div>
        )}
      </GlassCard>
    </motion.div>
  );
}
