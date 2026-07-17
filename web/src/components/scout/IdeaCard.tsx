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

// The score-engine fallback fills thesis/catalysts/risks with generic boilerplate
// that just repeats the score or states the obvious. Drop it so cards surface
// real signal (and look clean) instead of the same three lines on every card.
const BOILERPLATE = [
  /^alpha scout composite score/i,
  /^composite score\b/i,
  /^conviction:/i,
  /^requires follow-up council/i,
  /^quantitative screen may miss/i,
  /^alpha scout ranked /i,
];

function meaningful(text?: string): string {
  const trimmed = (text || "").trim();
  if (!trimmed) return "";
  return BOILERPLATE.some((re) => re.test(trimmed)) ? "" : trimmed;
}

function meaningfulList(items?: string[]): string[] {
  return (items || []).map(meaningful).filter(Boolean);
}

// theme arrives as "Portfolio · Communication Services" (source · sector) —
// split into individual chips, ignoring anything that just echoes the ticker.
function metaChips(idea: BackendTopIdea): string[] {
  const ticker = idea.ticker?.toUpperCase();
  return (idea.theme || "")
    .split("·")
    .map((part) => part.trim())
    .filter((part) => part && part.toUpperCase() !== ticker);
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
  const company = idea.company?.trim() && idea.company.trim().toUpperCase() !== idea.ticker?.toUpperCase()
    ? idea.company.trim()
    : "";
  const chips = metaChips(idea);
  const thesis = meaningful(idea.thesis);
  const catalysts = meaningfulList(idea.catalysts).slice(0, 2);
  const risks = meaningfulList(idea.risks).slice(0, 2);

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
          <div className="flex min-w-0 items-start gap-3">
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-(--color-surface-elevated) font-mono text-xs font-bold text-(--color-text-tertiary)">
              {idea.rank}
            </span>
            <div className="min-w-0">
              <h3 className="font-mono text-xl font-bold leading-none tracking-tight text-(--color-text-primary)">
                {idea.ticker}
              </h3>
              {company && <p className="mt-1 truncate text-xs text-(--color-text-tertiary)">{company}</p>}
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <span className={`font-mono text-3xl font-bold leading-none tabular-nums ${tier.text}`}>{score}</span>
            <StatusBadge variant={tier.badge}>{tier.label}</StatusBadge>
          </div>
        </div>

        {/* Meta chips: source · sector */}
        {chips.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {chips.map((chip) => (
              <span
                key={chip}
                className="rounded-md border border-(--color-border-subtle) bg-(--color-surface-elevated)/40 px-2 py-0.5 text-[11px] font-medium text-(--color-text-tertiary)"
              >
                {chip}
              </span>
            ))}
          </div>
        )}

        {/* Tier-calibrated score meter */}
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
          <motion.div
            className={`h-full rounded-full ${tier.bar}`}
            initial={{ width: 0 }}
            animate={{ width: `${Math.max(0, Math.min(100, score))}%` }}
            transition={{ duration: reducedMotion ? 0 : 0.8, delay: reducedMotion ? 0 : index * 0.05 + 0.15, ease: [0.25, 0.46, 0.45, 0.94] }}
          />
        </div>

        {/* Thesis (only when it carries real signal) */}
        {thesis && (
          <p className="mt-4 line-clamp-3 text-[13px] leading-relaxed text-(--color-text-secondary)">{thesis}</p>
        )}

        {/* Real catalysts / risks */}
        {(catalysts.length > 0 || risks.length > 0) && (
          <div className="mt-4 space-y-1.5">
            {catalysts.map((catalyst) => (
              <div key={catalyst} className="flex items-start gap-2">
                <TrendingUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-(--color-accent-emerald)" />
                <span className="line-clamp-2 text-[12px] leading-relaxed text-(--color-text-secondary)">{catalyst}</span>
              </div>
            ))}
            {risks.map((risk) => (
              <div key={risk} className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-(--color-accent-amber)" />
                <span className="line-clamp-2 text-[12px] leading-relaxed text-(--color-text-secondary)">{risk}</span>
              </div>
            ))}
          </div>
        )}

        {/* Footer pinned to the bottom */}
        <div className="mt-4 flex flex-1 items-end">
          <div className="flex w-full items-center gap-2 border-t border-(--color-border-subtle) pt-3.5">
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
        </div>
      </GlassCard>
    </motion.div>
  );
}
