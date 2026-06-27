import { motion } from "motion/react";
import { BrainCircuit, TrendingUp, AlertTriangle } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { BackendTopIdea } from "@/types";
import { GlassCard, type GlowColor } from "@/components/ui/GlassCard";
import { GlassButton } from "@/components/ui/GlassButton";
import { StatusBadge, type StatusVariant } from "@/components/ui/StatusBadge";
import { useReducedMotion } from "@/lib/useReducedMotion";

// Conviction tiers on the 0–100 scale (mirrors the score-engine calibration).
interface Tier {
  label: string;
  text: string;
  bar: string;
  glow: GlowColor;
  badge: StatusVariant;
}

function tierFor(score100: number): Tier {
  if (score100 >= 90)
    return { label: "Conviction", text: "text-(--color-accent-violet)", bar: "bg-(--color-accent-violet)", glow: "violet", badge: "info" };
  if (score100 >= 70)
    return { label: "Strong", text: "text-(--color-accent-cyan)", bar: "bg-(--color-accent-cyan)", glow: "cyan", badge: "info" };
  if (score100 >= 50)
    return { label: "Moderate", text: "text-(--color-accent-emerald)", bar: "bg-(--color-accent-emerald)", glow: "emerald", badge: "success" };
  if (score100 >= 30)
    return { label: "Weak", text: "text-(--color-accent-amber)", bar: "bg-(--color-accent-amber)", glow: "amber", badge: "warning" };
  return { label: "Avoid", text: "text-(--color-accent-rose)", bar: "bg-(--color-accent-rose)", glow: "rose", badge: "critical" };
}

// Never repeat the ticker as its own sublabel (backend falls company → ticker).
function subLabel(idea: BackendTopIdea): string {
  const ticker = idea.ticker?.toUpperCase();
  const company = idea.company?.trim();
  if (company && company.toUpperCase() !== ticker) return company;
  const theme = idea.theme?.trim();
  if (theme && theme.toUpperCase() !== ticker) return theme;
  return "";
}

interface IdeaCardProps {
  idea: BackendTopIdea;
  index: number;
}

export function IdeaCard({ idea, index }: IdeaCardProps) {
  const reducedMotion = useReducedMotion();
  const navigate = useNavigate();
  const score = Math.round(idea.score * 100);
  const tier = tierFor(score);
  const sub = subLabel(idea);
  const catalyst = idea.catalysts?.[0]?.trim();
  const risk = idea.risks?.[0]?.trim();

  return (
    <motion.div
      className="h-full"
      initial={reducedMotion ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: reducedMotion ? 0 : index * 0.05, ease: [0.25, 0.46, 0.45, 0.94] }}
    >
      <GlassCard glow={tier.glow} hoverLift className="flex h-full flex-col p-5">
        {/* Header: rank · ticker · company / score · tier */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-(--color-surface-elevated) font-mono text-xs font-bold text-(--color-text-tertiary)">
              #{idea.rank}
            </span>
            <div className="min-w-0">
              <h3 className="font-mono text-lg font-bold tracking-tight text-(--color-text-primary)">{idea.ticker}</h3>
              {sub && <p className="truncate text-xs text-(--color-text-tertiary)">{sub}</p>}
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <span className={`font-mono text-2xl font-bold tabular-nums ${tier.text}`}>{score}</span>
            <StatusBadge variant={tier.badge}>{tier.label}</StatusBadge>
          </div>
        </div>

        {/* Score bar */}
        <div className="mt-4">
          <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
            <motion.div
              className={`h-full rounded-full ${tier.bar}`}
              initial={{ width: 0 }}
              animate={{ width: `${Math.max(0, Math.min(100, score))}%` }}
              transition={{ duration: reducedMotion ? 0 : 0.8, delay: reducedMotion ? 0 : index * 0.05 + 0.15, ease: [0.25, 0.46, 0.45, 0.94] }}
            />
          </div>
        </div>

        {/* Thesis */}
        <p className="mt-4 line-clamp-3 flex-1 text-[13px] leading-relaxed text-(--color-text-secondary)">
          {idea.thesis}
        </p>

        {/* Catalyst / risk chips */}
        {(catalyst || risk) && (
          <div className="mt-4 space-y-1.5">
            {catalyst && (
              <div className="flex items-start gap-2 rounded-lg bg-(--color-surface-elevated)/40 px-3 py-1.5">
                <TrendingUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-(--color-accent-emerald)" />
                <span className="line-clamp-1 text-[11px] leading-relaxed text-(--color-text-secondary)">{catalyst}</span>
              </div>
            )}
            {risk && (
              <div className="flex items-start gap-2 rounded-lg bg-(--color-surface-elevated)/40 px-3 py-1.5">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-(--color-accent-amber)" />
                <span className="line-clamp-1 text-[11px] leading-relaxed text-(--color-text-secondary)">{risk}</span>
              </div>
            )}
          </div>
        )}

        {/* Footer: horizon + council CTA */}
        <div className="mt-4 flex items-center gap-2 border-t border-(--color-border-subtle) pt-4">
          {idea.horizon && (
            <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-(--color-text-tertiary)">
              {idea.horizon}
            </span>
          )}
          <GlassButton
            type="button"
            variant="ghost"
            leftIcon={<BrainCircuit className="h-4 w-4" />}
            onClick={() => navigate(`/council?ticker=${idea.ticker}&run=1&from=scout`)}
            className="ml-auto"
          >
            Council deep dive
          </GlassButton>
        </div>
      </GlassCard>
    </motion.div>
  );
}
