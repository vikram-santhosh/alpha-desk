import { useCallback, useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { RefreshCw, Wallet } from "lucide-react";
import { fetchPortfolioSnapshot } from "@/lib/api";
import { rise, stagger } from "@/lib/motion";
import type { PortfolioSnapshot, Rating } from "@/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlassButton } from "@/components/ui/GlassButton";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";

const ratingVariant: Record<Rating, "info" | "success" | "warning" | "critical" | "neutral"> = {
  Buy: "success",
  Overweight: "info",
  Hold: "neutral",
  Underweight: "warning",
  Sell: "critical",
};

export default function BackendPortfolioView() {
  const reduceMotion = useReducedMotion();
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSnapshot(await fetchPortfolioSnapshot());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load backend portfolio");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedPositions = useMemo(
    () => [...(snapshot?.positions ?? [])].sort((a, b) => b.weight_pct - a.weight_pct),
    [snapshot]
  );

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl space-y-6">
        <Skeleton className="h-10 w-56" />
        <div className="grid gap-4 md:grid-cols-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (error || !snapshot) {
    return (
      <div className="mx-auto max-w-7xl">
        <EmptyState
          title="Backend portfolio unavailable"
          description={error ?? "FastAPI did not return a portfolio snapshot."}
          icon={<Wallet className="h-6 w-6" />}
          action={{ label: "Retry", onClick: load }}
        />
      </div>
    );
  }

  return (
    <motion.div
      className="mx-auto max-w-7xl space-y-6"
      variants={stagger}
      initial={reduceMotion ? "visible" : "hidden"}
      animate="visible"
    >
      <motion.header variants={rise} className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Wallet className="h-5 w-5 text-(--color-accent-cyan)" />
            <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">Portfolio</h1>
          </div>
          <p className="mt-1 text-sm text-(--color-text-secondary)">
            Live holdings and concentration flags from `/api/portfolio`.
          </p>
        </div>
        <GlassButton
          variant="ghost"
          onClick={load}
          disabled={loading}
          leftIcon={<RefreshCw className="h-4 w-4" />}
        >
          Refresh
        </GlassButton>
      </motion.header>

      <motion.div variants={rise} className="grid gap-4 md:grid-cols-3">
        <GlassCard className="p-5" hoverLift={false}>
          <p className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">Positions</p>
          <p className="mt-2 font-mono text-3xl text-(--color-text-primary)">{snapshot.positions.length}</p>
        </GlassCard>
        <GlassCard className="p-5" hoverLift={false}>
          <p className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">Top holding</p>
          <p className="mt-2 font-mono text-3xl text-(--color-text-primary)">{snapshot.top_holding_pct.toFixed(1)}%</p>
        </GlassCard>
        <GlassCard className="p-5" glow={snapshot.concentration_flag ? "rose" : "emerald"} hoverLift={false}>
          <p className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">Concentration</p>
          <p className="mt-2 font-mono text-3xl text-(--color-text-primary)">{snapshot.top3_pct.toFixed(1)}%</p>
          <p className="mt-2 text-xs text-(--color-text-secondary)">
            {snapshot.concentration_flag ? "Flagged by backend threshold" : "Within backend threshold"}
          </p>
        </GlassCard>
      </motion.div>

      <motion.div variants={rise}>
        <GlassCard className="overflow-hidden" hoverLift={false}>
          <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3 border-b border-(--color-border-subtle) px-4 py-3 text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">
            <span>Ticker</span>
            <span>Rating</span>
            <span className="text-right">Weight</span>
          </div>
          <div className="divide-y divide-(--color-border-subtle)">
            {sortedPositions.map((position) => (
              <div key={position.ticker} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 px-4 py-3">
                <span className="min-w-0 truncate font-mono text-sm text-(--color-text-primary)">{position.ticker}</span>
                {position.rating ? (
                  <StatusBadge variant={ratingVariant[position.rating]}>{position.rating}</StatusBadge>
                ) : (
                  <StatusBadge>Unrated</StatusBadge>
                )}
                <span className="text-right font-mono text-sm text-(--color-text-secondary)">{position.weight_pct.toFixed(2)}%</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
