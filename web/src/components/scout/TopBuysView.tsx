import { useCallback, useEffect, useState } from "react";
import { motion } from "motion/react";
import { ArrowUpRight, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { BackendTopIdea, IdeaScoutResult } from "@/types";
import { fetchIdeaScout, fetchLatestIdeaScout } from "@/lib/api";
import { GlassCard, type GlowColor } from "@/components/ui/GlassCard";
import { GlassButton } from "@/components/ui/GlassButton";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { useReducedMotion } from "@/lib/useReducedMotion";

// Conviction tiers — same calibration the dashboard ScoreCard uses, on a
// 0–100 scale. Each tier carries a colour so the ranked list reads as
// calibrated (not a flat wall of identical numbers).
interface Tier {
  label: string;
  text: string;
  accent: string;
  glow: GlowColor;
}

function tierFor(score100: number): Tier {
  if (score100 >= 90)
    return { label: "Conviction", text: "text-(--color-accent-violet)", accent: "bg-(--color-accent-violet)", glow: "violet" };
  if (score100 >= 70)
    return { label: "Strong", text: "text-(--color-accent-cyan)", accent: "bg-(--color-accent-cyan)", glow: "cyan" };
  if (score100 >= 50)
    return { label: "Moderate", text: "text-(--color-accent-emerald)", accent: "bg-(--color-accent-emerald)", glow: "emerald" };
  if (score100 >= 30)
    return { label: "Weak", text: "text-(--color-accent-amber)", accent: "bg-(--color-accent-amber)", glow: "amber" };
  return { label: "Avoid", text: "text-(--color-accent-rose)", accent: "bg-(--color-accent-rose)", glow: "rose" };
}

// Secondary label next to the ticker: company name, or the theme — but never
// the ticker itself (the backend falls company back to the ticker, which would
// render "AFRM AFRM").
function subLabel(idea: BackendTopIdea): string {
  const ticker = idea.ticker?.toUpperCase();
  const company = idea.company?.trim();
  if (company && company.toUpperCase() !== ticker) return company;
  const theme = idea.theme?.trim();
  if (theme && theme.toUpperCase() !== ticker) return theme;
  return "";
}

export default function TopBuysView() {
  const [ideas, setIdeas] = useState<BackendTopIdea[]>([]);
  const [loading, setLoading] = useState(false);
  const [hydrating, setHydrating] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const reducedMotion = useReducedMotion();

  const apply = useCallback((data: IdeaScoutResult) => {
    setIdeas([...data.ideas].sort((a, b) => a.rank - b.rank));
  }, []);

  // Show the last saved run immediately — no clicking required to see something.
  useEffect(() => {
    let active = true;
    fetchLatestIdeaScout("top_buys")
      .then((data) => { if (active && data) apply(data); })
      .catch(() => { /* first-run: nothing saved yet, that's fine */ })
      .finally(() => { if (active) setHydrating(false); });
    return () => { active = false; };
  }, [apply]);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      apply(await fetchIdeaScout("top_buys", 10));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load top buys");
    } finally {
      setLoading(false);
    }
  }, [apply]);

  const showSkeleton = (hydrating || loading) && ideas.length === 0;

  return (
    <section className="mx-auto max-w-3xl space-y-6">
      <motion.header
        className="flex items-center justify-between gap-4"
        initial={reducedMotion ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">Top Buys</h1>
          <p className="mt-1 text-sm text-(--color-text-secondary)">Highest-conviction names right now.</p>
        </div>
        <GlassButton
          variant="solid"
          leftIcon={<RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />}
          onClick={() => void run()}
          disabled={loading}
        >
          {loading ? "Finding…" : "Get top buys"}
        </GlassButton>
      </motion.header>

      {showSkeleton ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-16" />)}
        </div>
      ) : error && ideas.length === 0 ? (
        <GlassCard glow="rose" className="p-6">
          <EmptyState title="Couldn’t load top buys" description={error}
            action={{ label: "Try again", onClick: () => void run() }} />
        </GlassCard>
      ) : ideas.length === 0 ? (
        <GlassCard className="p-8" hoverLift={false}>
          <EmptyState title="No top buys yet" description="Press “Get top buys” to run the ranking."
            action={{ label: "Get top buys", onClick: () => void run() }} />
        </GlassCard>
      ) : (
        <div className="space-y-1.5">
          {ideas.map((idea, i) => {
            const score = Math.round(idea.score * 100);
            const tier = tierFor(score);
            const sub = subLabel(idea);
            return (
              <motion.button
                key={`${idea.ticker}-${idea.rank}`}
                type="button"
                onClick={() => navigate(`/council?ticker=${idea.ticker}&run=1&from=scout`)}
                className="group block w-full text-left"
                initial={reducedMotion ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: reducedMotion ? 0 : i * 0.03 }}
              >
                <GlassCard hoverLift glow={i === 0 ? tier.glow : false} className="relative overflow-hidden p-0">
                  {/* tier-coloured rail — gives the ranked list colour rhythm */}
                  <span className={`absolute inset-y-0 left-0 w-[3px] ${tier.accent}`} aria-hidden />
                  <div className="flex items-center gap-4 py-3 pl-5 pr-4">
                    <span className="w-5 shrink-0 text-center font-mono text-sm tabular-nums text-(--color-text-tertiary)">
                      {idea.rank}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <span className="font-mono text-[15px] font-semibold tracking-tight text-(--color-text-primary)">
                          {idea.ticker}
                        </span>
                        {sub && <span className="truncate text-xs text-(--color-text-tertiary)">{sub}</span>}
                      </div>
                      <p className="mt-1 line-clamp-1 text-[13px] leading-snug text-(--color-text-secondary)">
                        {idea.thesis}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end leading-none">
                      <span className={`font-mono text-xl font-bold tabular-nums ${tier.text}`}>{score}</span>
                      <span className={`mt-1 text-[10px] font-medium uppercase tracking-[0.08em] ${tier.text} opacity-70`}>
                        {tier.label}
                      </span>
                    </div>
                    <ArrowUpRight className="h-4 w-4 shrink-0 text-(--color-text-tertiary) opacity-0 transition-opacity group-hover:opacity-100" />
                  </div>
                  {/* subtle score meter — clustered high scores read as calibrated */}
                  <span className="absolute inset-x-0 bottom-0 h-px bg-(--color-border-subtle)" aria-hidden />
                  <span
                    className={`absolute bottom-0 left-0 h-px ${tier.accent} opacity-60`}
                    style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
                    aria-hidden
                  />
                </GlassCard>
              </motion.button>
            );
          })}
        </div>
      )}
    </section>
  );
}
