import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { Activity, Calendar, TrendingUp } from "lucide-react";

import { GlassCard } from "@/components/ui/GlassCard";
import { Sparkline } from "@/components/ui/Sparkline";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { MockDataBadge } from "@/components/ui/MockDataBadge";
import { DeltaChip } from "@/components/ui/DeltaChip";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { GlassSelect } from "@/components/ui/GlassSelect";
import { fetchPredictionMarkets } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDate, formatPercent } from "@/lib/format";
import type { PredictionMarket } from "@/types";

type SortKey = "edge" | "probability" | "date";

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);

    const handler = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return reduced;
}

function sortMarkets(
  markets: PredictionMarket[],
  sort: SortKey
): PredictionMarket[] {
  const next = [...markets];
  switch (sort) {
    case "edge":
      return next.sort(
        (a, b) =>
          Math.abs(b.modelEstimate - b.probability) -
          Math.abs(a.modelEstimate - a.probability)
      );
    case "probability":
      return next.sort((a, b) => b.probability - a.probability);
    case "date":
      return next.sort(
        (a, b) =>
          new Date(a.resolutionDate).getTime() -
          new Date(b.resolutionDate).getTime()
      );
    default:
      return next;
  }
}

function sparklineColor(
  data: PredictionMarket["sevenDaySparkline"]
): "emerald" | "rose" | "cyan" {
  if (data.length < 2) return "cyan";
  const start = data[0].value;
  const end = data[data.length - 1].value;
  return end >= start ? "emerald" : "rose";
}

interface ProbabilityBarProps {
  label: string;
  value: number;
  color: "cyan" | "violet";
  reducedMotion: boolean;
  delay?: number;
}

function ProbabilityBar({
  label,
  value,
  color,
  reducedMotion,
  delay = 0,
}: ProbabilityBarProps) {
  const fillPct = Math.min(Math.max(value, 0), 100);
  const colorClass =
    color === "cyan"
      ? "bg-(--color-accent-cyan)"
      : "bg-(--color-accent-violet)";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-(--color-text-secondary)">
          {label}
        </span>
        <span className="tabular-nums text-(--color-text-primary)">
          {formatPercent(value, false)}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
        <motion.div
          className={cn("h-full rounded-full", colorClass)}
          initial={{ width: 0 }}
          animate={{ width: `${fillPct}%` }}
          transition={
            reducedMotion
              ? { duration: 0 }
              : { duration: 0.8, delay, ease: [0.25, 0.46, 0.45, 0.94] }
          }
        />
      </div>
    </div>
  );
}

function PositionChip({
  position,
}: {
  position: PredictionMarket["position"];
}) {
  if (!position) {
    return <StatusBadge variant="neutral">No position</StatusBadge>;
  }

  if (position === "yes") {
    return (
      <StatusBadge variant="success" icon={<TrendingUp className="h-3 w-3" />}>
        Long Yes
      </StatusBadge>
    );
  }

  return (
    <StatusBadge variant="critical" icon={<TrendingUp className="h-3 w-3 rotate-180" />}>
      Short No
    </StatusBadge>
  );
}

interface MarketCardProps {
  market: PredictionMarket;
  index: number;
  reducedMotion: boolean;
}

function MarketCard({ market, index, reducedMotion }: MarketCardProps) {
  const edge = market.modelEstimate - market.probability;
  const sparkColor = sparklineColor(market.sevenDaySparkline);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={
        reducedMotion
          ? { duration: 0 }
          : {
              duration: 0.4,
              delay: index * 0.06,
              ease: [0.25, 0.46, 0.45, 0.94],
            }
      }
    >
      <GlassCard className="flex flex-col gap-5 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-base font-semibold leading-snug text-(--color-text-primary)">
              {market.question}
            </h3>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge variant="neutral">{market.source}</StatusBadge>
              <PositionChip position={market.position} />
            </div>
          </div>
        </div>

        <div className="flex items-end gap-3">
          <span className="text-4xl font-semibold tracking-tight text-(--color-text-primary) tabular-nums">
            {formatPercent(market.probability, false)}
          </span>
          <span className="mb-1.5 text-xs text-(--color-text-secondary)">
            market probability
          </span>
        </div>

        <ProbabilityBar
          label="Market probability"
          value={market.probability}
          color="cyan"
          reducedMotion={reducedMotion}
          delay={0.1}
        />
        <ProbabilityBar
          label="AlphaDesk model"
          value={market.modelEstimate}
          color="violet"
          reducedMotion={reducedMotion}
          delay={0.2}
        />

        <div className="flex items-center justify-between rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/50 px-3 py-2">
          <span className="text-xs text-(--color-text-secondary)">
            Edge vs model
          </span>
          <DeltaChip value={edge} />
        </div>

        <div className="flex items-center gap-3">
          <Sparkline
            data={market.sevenDaySparkline}
            color={sparkColor}
            height={48}
            className="flex-1"
          />
          <div className="flex flex-col items-end text-xs text-(--color-text-secondary)">
            <span className="flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              Resolves
            </span>
            <span className="tabular-nums text-(--color-text-primary)">
              {formatDate(market.resolutionDate)}
            </span>
          </div>
        </div>
      </GlassCard>
    </motion.div>
  );
}

function MarketsSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <GlassCard key={i} className="flex flex-col gap-5 p-5" hoverLift={false}>
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-2 w-full" />
          <Skeleton className="h-2 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-12 w-full" />
        </GlassCard>
      ))}
    </div>
  );
}

export default function MarketsView() {
  const [markets, setMarkets] = useState<PredictionMarket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("edge");
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchPredictionMarkets()
      .then((data) => {
        if (!cancelled) setMarkets(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Failed to load prediction markets"
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const sorted = useMemo(() => sortMarkets(markets, sort), [markets, sort]);

  return (
    <section className="mx-auto max-w-7xl space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">
              Prediction Markets
            </h1>
            <MockDataBadge />
          </div>
          <p className="text-sm text-(--color-text-secondary)">
            Tracked markets with AlphaDesk model edge.
          </p>
        </div>
        <GlassSelect
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="w-full sm:w-48"
          aria-label="Sort markets"
        >
          <option value="edge">Sort by edge</option>
          <option value="probability">Sort by probability</option>
          <option value="date">Sort by resolution date</option>
        </GlassSelect>
      </div>

      {loading && <MarketsSkeleton />}

      {!loading && error && (
        <GlassCard glow="rose" className="p-6">
          <p className="text-sm text-(--color-accent-rose)">{error}</p>
        </GlassCard>
      )}

      {!loading && !error && sorted.length === 0 && (
        <EmptyState
          title="No markets tracked"
          description="Add prediction markets to your watchlist to see them here."
          icon={<Activity className="h-6 w-6" />}
        />
      )}

      {!loading && !error && sorted.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {sorted.map((market, index) => (
            <MarketCard
              key={market.id}
              market={market}
              index={index}
              reducedMotion={reducedMotion}
            />
          ))}
        </div>
      )}
    </section>
  );
}
