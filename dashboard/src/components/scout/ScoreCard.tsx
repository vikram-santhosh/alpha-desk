import type { TopBuyScore } from "@/types";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassButton } from "@/components/ui/GlassButton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { motion } from "motion/react";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { BrainCircuit, TrendingDown, TrendingUp, Minus } from "lucide-react";
import { useNavigate } from "react-router-dom";

interface ScoreCardProps {
  entry: TopBuyScore;
  rank: number;
  index: number;
}

// Tiers mirror the calibration rubric in docs/ALPHADESK.md.
const TIER_CONFIG = {
  conviction: { label: "Conviction", glow: "violet" as const, bar: "bg-(--color-accent-violet)",  text: "text-(--color-accent-violet)"  },
  strong:     { label: "Strong",     glow: "cyan"   as const, bar: "bg-(--color-accent-cyan)",    text: "text-(--color-accent-cyan)"    },
  moderate:   { label: "Moderate",   glow: false    as const, bar: "bg-(--color-accent-emerald)", text: "text-(--color-accent-emerald)" },
  weak:       { label: "Weak",       glow: false    as const, bar: "bg-(--color-accent-amber)",   text: "text-(--color-accent-amber)"   },
  avoid:      { label: "Avoid",      glow: "rose"   as const, bar: "bg-(--color-accent-rose)",    text: "text-(--color-accent-rose)"    },
};

function getTier(score: number) {
  if (score >= 8.5) return TIER_CONFIG.conviction;
  if (score >= 7)   return TIER_CONFIG.strong;
  if (score >= 5)   return TIER_CONFIG.moderate;
  if (score >= 3)   return TIER_CONFIG.weak;
  return TIER_CONFIG.avoid;
}

function DirectionIcon({ direction }: { direction: string }) {
  if (direction === "BULL") return <TrendingUp  className="h-3.5 w-3.5 text-(--color-accent-emerald) shrink-0" />;
  if (direction === "BEAR") return <TrendingDown className="h-3.5 w-3.5 text-(--color-accent-rose)    shrink-0" />;
  return <Minus className="h-3.5 w-3.5 text-(--color-text-tertiary) shrink-0" />;
}

export function ScoreCard({ entry, rank, index }: ScoreCardProps) {
  const reducedMotion = useReducedMotion();
  const navigate = useNavigate();
  const tier = getTier(entry.score);
  const scorePct = (entry.score / 10) * 100;
  const bullBreakdown = entry.breakdown.filter(b => b.direction === "BULL");
  const bearBreakdown = entry.breakdown.filter(b => b.direction === "BEAR");
  const neutralBreakdown = entry.breakdown.filter(b => b.direction === "NEUTRAL");

  const openCouncil = () => {
    const params = new URLSearchParams({ ticker: entry.ticker, run: "1", from: "scout" });
    navigate(`/council?${params.toString()}`);
  };

  return (
    <motion.div
      className="h-full"
      initial={reducedMotion ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.45,
        delay: reducedMotion ? 0 : index * 0.07,
        ease: [0.25, 0.46, 0.45, 0.94],
      }}
    >
      <GlassCard glow={tier.glow || false} hoverLift className="flex h-full flex-col p-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-(--color-surface-elevated) font-mono text-xs font-bold text-(--color-text-tertiary)">
              #{rank}
            </span>
            <div className="min-w-0">
              <h3 className="font-mono text-lg font-bold text-(--color-text-primary)">{entry.ticker}</h3>
              <p className="text-xs text-(--color-text-tertiary)">
                {entry.platforms_reporting.length} platform{entry.platforms_reporting.length !== 1 ? "s" : ""}
              </p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1.5 shrink-0">
            <span className={`font-mono text-2xl font-bold tabular-nums ${tier.text}`}>
              {entry.score.toFixed(2)}
              <span className="text-sm font-normal text-(--color-text-tertiary)">/10</span>
            </span>
            <StatusBadge variant={
              tier === TIER_CONFIG.conviction ? "success" :
              tier === TIER_CONFIG.strong ? "info" :
              tier === TIER_CONFIG.avoid ? "critical" : "warning"
            }>
              {tier.label}
            </StatusBadge>
          </div>
        </div>

        {/* Score bar */}
        <div className="mt-4">
          <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
            <motion.div
              className={`h-full rounded-full ${tier.bar}`}
              initial={{ width: 0 }}
              animate={{ width: `${scorePct}%` }}
              transition={{
                duration: reducedMotion ? 0 : 0.9,
                delay: reducedMotion ? 0 : index * 0.07 + 0.2,
                ease: [0.25, 0.46, 0.45, 0.94],
              }}
            />
          </div>
          <div className="mt-1.5 flex justify-between">
            {[2, 4, 6, 8, 10].map(tick => (
              <span key={tick} className={`font-mono text-[10px] ${entry.score >= tick ? tier.text : "text-(--color-text-tertiary)/40"}`}>
                {tick}
              </span>
            ))}
          </div>
        </div>

        {/* Platform tags */}
        <div className="mt-4 flex flex-wrap gap-1.5">
          {entry.platforms_reporting.map(p => (
            <span key={p} className="rounded-md border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 px-2 py-0.5 font-mono text-[10px] text-(--color-text-secondary)">
              {p}
            </span>
          ))}
          {entry.platforms_failed.length > 0 && (
            <span className="rounded-md border border-(--color-accent-rose)/20 bg-(--color-accent-rose)/10 px-2 py-0.5 font-mono text-[10px] text-(--color-accent-rose)">
              {entry.platforms_failed.length} failed
            </span>
          )}
        </div>

        {/* Breakdown */}
        <div className="mt-4 flex-1 space-y-2">
          {[...bullBreakdown, ...neutralBreakdown, ...bearBreakdown].map((b, i) => (
            <div key={i} className="flex items-start gap-2 rounded-lg bg-(--color-surface-elevated)/40 px-3 py-2">
              <DirectionIcon direction={b.direction} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-medium text-(--color-text-primary)">{b.sensor}</span>
                  <span className={`font-mono text-xs tabular-nums ${b.contribution > 0 ? "text-(--color-accent-emerald)" : b.contribution < 0 ? "text-(--color-accent-rose)" : "text-(--color-text-tertiary)"}`}>
                    {b.contribution > 0 ? "+" : ""}{b.contribution.toFixed(3)}
                  </span>
                </div>
                <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-(--color-text-secondary)">
                  {b.evidence}
                </p>
                <div className="mt-1 flex gap-3 text-[10px] text-(--color-text-tertiary)">
                  <span>str {(b.strength * 100).toFixed(0)}%</span>
                  <span>conf {(b.confidence * 100).toFixed(0)}%</span>
                  <span>wt {b.weight.toFixed(1)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="mt-4 border-t border-(--color-border-subtle) pt-4">
          <GlassButton
            type="button"
            variant="ghost"
            leftIcon={<BrainCircuit className="h-4 w-4" />}
            onClick={openCouncil}
            className="w-full"
          >
            Council deep dive
          </GlassButton>
        </div>
      </GlassCard>
    </motion.div>
  );
}
