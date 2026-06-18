import { motion, useReducedMotion } from "motion/react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Gauge } from "@/components/ui/Gauge";
import { AgentTag } from "@/components/ui/AgentTag";
import { StreamingText } from "@/components/ui/StreamingText";
import { Skeleton } from "@/components/ui/Skeleton";
import type { MacroRegime } from "@/types";
import { minutesAgo } from "./utils";
import { rise } from "@/lib/motion";

interface MacroRegimeSectionProps {
  regime: MacroRegime | null;
  loading: boolean;
}

export function MacroRegimeSection({ regime, loading }: MacroRegimeSectionProps) {
  const reduceMotion = useReducedMotion();

  if (loading || !regime) {
    return (
      <GlassCard className="p-6">
        <div className="flex flex-col items-center gap-6 md:flex-row md:items-start">
          <Skeleton className="h-32 w-48" />
          <div className="flex-1 space-y-3">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-8 w-32" />
          </div>
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard
      as={motion.div}
      variants={rise}
      initial={reduceMotion ? "visible" : "hidden"}
      animate="visible"
      glow="violet"
      className="p-6"
    >
      <div className="flex flex-col items-center gap-6 md:flex-row md:items-start">
        <div className="flex flex-col items-center">
          <Gauge value={regime.score} min={0} max={100} size={160} strokeWidth={12} />
          <div className="mt-2 flex w-full justify-between px-2 text-[10px] font-medium uppercase tracking-wider text-(--color-text-tertiary)">
            <span className="text-(--color-accent-rose)">Risk-Off</span>
            <span className="text-(--color-accent-emerald)">Risk-On</span>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-2xl font-bold text-(--color-text-primary)">{regime.call}</h2>
            <AgentTag name={regime.agent} confidence={regime.score} />
          </div>

          <StreamingText
            text={regime.rationale}
            speed={28}
            showScanline
            className="text-sm leading-relaxed text-(--color-text-secondary)"
          />

          <div className="mt-1 text-xs text-(--color-text-tertiary)">
            Scanned {minutesAgo(regime.scannedAt)}
          </div>
        </div>
      </div>
    </GlassCard>
  );
}
