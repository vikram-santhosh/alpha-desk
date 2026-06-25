import { motion, useReducedMotion } from "motion/react";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { MacroTheme } from "@/types";
import type { GlowColor } from "@/components/ui/GlassCard";
import { rise } from "@/lib/motion";

interface MacroThemeCardProps {
  theme: MacroTheme;
}

const statusAccent: Record<MacroTheme["status"], GlowColor> = {
  risk_on: "emerald",
  neutral: "amber",
  risk_off: "rose",
};

const statusLabel: Record<MacroTheme["status"], string> = {
  risk_on: "Risk-On",
  neutral: "Neutral",
  risk_off: "Risk-Off",
};

const trendIcon = {
  up: ArrowUp,
  down: ArrowDown,
  flat: Minus,
};

const trendAccent: Record<MacroTheme["trend"], GlowColor> = {
  up: "emerald",
  down: "rose",
  flat: "amber",
};

export function MacroThemeCard({ theme }: MacroThemeCardProps) {
  const reduceMotion = useReducedMotion();
  const accent = statusAccent[theme.status];
  const TrendIcon = trendIcon[theme.trend];
  const trendColor = trendAccent[theme.trend];

  return (
    <GlassCard
      as={motion.div}
      variants={rise}
      initial={reduceMotion ? "visible" : "hidden"}
      animate="visible"
      glow={accent}
      className="flex h-full flex-col p-5"
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-(--color-text-primary)">{theme.title}</h3>
          <span className="text-xs text-(--color-text-tertiary)">{statusLabel[theme.status]}</span>
        </div>
        <div
          className={`flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-medium tabular-nums ${
            trendColor === "emerald"
              ? "border-(--color-accent-emerald)/20 text-(--color-accent-emerald)"
              : trendColor === "rose"
                ? "border-(--color-accent-rose)/20 text-(--color-accent-rose)"
                : "border-(--color-accent-amber)/20 text-(--color-accent-amber)"
          }`}
        >
          <TrendIcon className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="uppercase">{theme.trend}</span>
        </div>
      </div>

      <div className="mb-4">
        <div className="mb-1.5 flex items-center justify-between text-xs text-(--color-text-secondary)">
          <span>Confidence</span>
          <span className="tabular-nums text-(--color-text-primary)">{theme.confidence}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-accent-violet)/15">
          <motion.div
            className="h-full rounded-full bg-(--color-accent-violet)"
            initial={{ width: reduceMotion ? `${theme.confidence}%` : "0%" }}
            animate={{ width: `${theme.confidence}%` }}
            transition={{ duration: 0.8, ease: [0.25, 0.46, 0.45, 0.94] }}
          />
        </div>
      </div>

      <ul className="mt-auto space-y-2">
        {theme.bullets.map((bullet, idx) => (
          <li key={idx} className="flex gap-2 text-sm text-(--color-text-secondary)">
            <span
              className={`mt-1.5 h-1 w-1 shrink-0 rounded-full ${
                accent === "emerald"
                  ? "bg-(--color-accent-emerald)"
                  : accent === "rose"
                    ? "bg-(--color-accent-rose)"
                    : "bg-(--color-accent-amber)"
              }`}
            />
            <span>{bullet}</span>
          </li>
        ))}
      </ul>
    </GlassCard>
  );
}
