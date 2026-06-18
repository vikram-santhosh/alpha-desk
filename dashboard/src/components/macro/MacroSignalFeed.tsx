import { motion, useReducedMotion } from "motion/react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { StreamingText } from "@/components/ui/StreamingText";
import type { MacroSignal } from "./utils";
import { minutesAgo } from "./utils";
import { stagger, rise } from "@/lib/motion";
import { Radio } from "lucide-react";

interface MacroSignalFeedProps {
  signals: MacroSignal[];
}

const impactVariant = {
  positive: "success" as const,
  neutral: "warning" as const,
  negative: "critical" as const,
};

const impactLabel = {
  positive: "Risk-On impulse",
  neutral: "Mixed signal",
  negative: "Risk-Off impulse",
};

export function MacroSignalFeed({ signals }: MacroSignalFeedProps) {
  const reduceMotion = useReducedMotion();

  if (signals.length === 0) {
    return (
      <GlassCard className="p-6">
        <EmptyState
          title="No macro signals"
          description="Macro scanner hasn’t emitted any theme signals yet."
          icon={<Radio className="h-5 w-5" />}
        />
      </GlassCard>
    );
  }

  return (
    <GlassCard className="overflow-hidden p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-base font-semibold text-(--color-text-primary)">Signal Feed</h3>
        <span className="text-xs text-(--color-text-tertiary)">
          {signals.length} scanned signals
        </span>
      </div>

      <motion.ul
        className="space-y-3"
        variants={stagger}
        initial={reduceMotion ? "visible" : "hidden"}
        animate="visible"
      >
        {signals.map((signal, idx) => (
          <motion.li
            key={signal.id}
            variants={rise}
            className="flex flex-col gap-2 rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/40 p-3.5 sm:flex-row sm:items-start sm:justify-between"
          >
            <div className="flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-(--color-text-secondary)">
                  {signal.themeTitle}
                </span>
                <StatusBadge variant={impactVariant[signal.impact]}>
                  {impactLabel[signal.impact]}
                </StatusBadge>
              </div>
              <StreamingText
                text={signal.text}
                speed={24}
                showScanline={false}
                className="text-sm leading-relaxed text-(--color-text-primary)"
              />
              <div className="mt-2 text-xs text-(--color-text-tertiary)">
                Source: {signal.source} • {minutesAgo(signal.scannedAt)}
              </div>
            </div>
            <div className="hidden text-xs tabular-nums text-(--color-text-tertiary) sm:block">
              #{String(signals.length - idx).padStart(2, "0")}
            </div>
          </motion.li>
        ))}
      </motion.ul>
    </GlassCard>
  );
}
