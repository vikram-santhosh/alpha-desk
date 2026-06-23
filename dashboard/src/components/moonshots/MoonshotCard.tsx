import type { Moonshot } from "@/types";
import { GlassCard } from "@/components/ui/GlassCard";
import { StreamingText } from "@/components/ui/StreamingText";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { motion } from "motion/react";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { ArrowBigDown, ArrowBigUp } from "lucide-react";

interface MoonshotCardProps {
  moonshot: Moonshot;
  index: number;
}

const sectorVariantMap: Record<string, "info" | "warning" | "critical" | "success" | "neutral"> = {
  Technology: "info",
  Energy: "warning",
  Defense: "critical",
  Commodities: "success",
};

export function MoonshotCard({ moonshot, index }: MoonshotCardProps) {
  const reducedMotion = useReducedMotion();
  const total = moonshot.asymmetry.downside + moonshot.asymmetry.upside;
  const upsidePct = total > 0 ? (moonshot.asymmetry.upside / total) * 100 : 50;

  return (
    <motion.div
      className="h-full"
      initial={reducedMotion ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.45,
        delay: reducedMotion ? 0 : index * 0.08,
        ease: [0.25, 0.46, 0.45, 0.94],
      }}
    >
      <GlassCard glow="violet" hoverLift className="flex h-full flex-col p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-base font-semibold text-(--color-text-primary)">
              {moonshot.name}
            </h3>
            <p className="mt-0.5 font-mono text-xs text-(--color-text-tertiary)">
              {moonshot.ticker}
            </p>
          </div>
          <StatusBadge variant={sectorVariantMap[moonshot.sector] ?? "neutral"}>
            {moonshot.sector}
          </StatusBadge>
        </div>

        <div className="mt-4">
          <p className="line-clamp-3 text-sm leading-relaxed text-(--color-text-secondary)">
            {moonshot.thesis}
          </p>
        </div>

        <div className="mt-5 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs font-medium text-(--color-text-secondary)">Conviction</span>
            <span className="text-xs font-semibold tabular-nums text-(--color-accent-violet)">
              {moonshot.conviction}%
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
            <motion.div
              className="h-full rounded-full bg-(--color-accent-violet)"
              initial={{ width: 0 }}
              animate={{ width: `${moonshot.conviction}%` }}
              transition={{
                duration: reducedMotion ? 0 : 0.9,
                delay: reducedMotion ? 0 : index * 0.08 + 0.2,
                ease: [0.25, 0.46, 0.45, 0.94],
              }}
            />
          </div>
        </div>

        <div className="mt-5 flex items-center gap-2 text-xs">
          <ArrowBigDown className="h-4 w-4 shrink-0 text-(--color-accent-rose)" aria-hidden="true" />
          <span className="tabular-nums text-(--color-accent-rose)">
            {moonshot.asymmetry.downside}%
          </span>
          <div className="relative mx-1 h-2 flex-1 overflow-hidden rounded-full bg-(--color-surface-elevated)">
            <motion.div
              className="absolute inset-y-0 left-0 rounded-full bg-(--color-accent-emerald)"
              initial={{ width: 0 }}
              animate={{ width: `${upsidePct}%` }}
              transition={{
                duration: reducedMotion ? 0 : 0.8,
                delay: reducedMotion ? 0 : index * 0.08 + 0.3,
                ease: [0.25, 0.46, 0.45, 0.94],
              }}
            />
            <motion.div
              className="absolute inset-y-0 rounded-full bg-(--color-accent-rose)"
              initial={{ right: "100%", left: 0 }}
              animate={{ right: 0, left: `${upsidePct}%` }}
              transition={{
                duration: reducedMotion ? 0 : 0.8,
                delay: reducedMotion ? 0 : index * 0.08 + 0.3,
                ease: [0.25, 0.46, 0.45, 0.94],
              }}
            />
          </div>
          <span className="tabular-nums text-(--color-accent-emerald)">
            {moonshot.asymmetry.upside}%
          </span>
          <ArrowBigUp className="h-4 w-4 shrink-0 text-(--color-accent-emerald)" aria-hidden="true" />
        </div>

        <div className="mt-auto border-t border-(--color-border-subtle) pt-4">
          <div className="mb-1.5 flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-tertiary)">
              Why now
            </span>
          </div>
          <StreamingText
            text={moonshot.whyNow}
            speed={22}
            showScanline={false}
            className="text-sm leading-relaxed text-(--color-text-secondary)"
          />
        </div>
      </GlassCard>
    </motion.div>
  );
}
