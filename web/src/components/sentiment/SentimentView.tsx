import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Brain,
  Frown,
  MessageCircle,
  RefreshCw,
  Smile,
  TrendingUp,
} from "lucide-react";

import type { SentimentTicker, SparklinePoint } from "@/types";
import { fetchSentimentTickers } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import { stagger, rise, fade } from "@/lib/motion";
import { GlassCard } from "@/components/ui/GlassCard";
import { Gauge } from "@/components/ui/Gauge";
import { Sparkline } from "@/components/ui/Sparkline";
import { DeltaChip } from "@/components/ui/DeltaChip";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { MockDataBadge } from "@/components/ui/MockDataBadge";
import { AgentTag } from "@/components/ui/AgentTag";
import { Drawer } from "@/components/ui/Drawer";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { GlassButton } from "@/components/ui/GlassButton";
import { Tooltip } from "@/components/ui/Tooltip";
import { StreamingText } from "@/components/ui/StreamingText";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useReducedMotion } from "@/lib/useReducedMotion";

interface SentimentPoint extends SparklinePoint {
  day: string;
}

type SortMode = "rank" | "volume" | "divergence";
type FilterMode = "all" | "bullish" | "bearish";

function generateSentimentHistory(volume: SparklinePoint[]): SentimentPoint[] {
  const min = Math.min(...volume.map((p) => p.value));
  const max = Math.max(...volume.map((p) => p.value));
  const range = max - min || 1;
  return volume.map((p, i) => {
    const normalized = Math.round(((p.value - min) / range) * 60 + 20);
    return {
      value: normalized,
      day: `D${i + 1}`,
    };
  });
}

function galaxyScore(ticker: SentimentTicker): number {
  return Math.round(
    ticker.socialScore * 0.45 +
      ticker.bullishPct * 0.35 +
      Math.min(Math.max(ticker.priceChangePct * 5 + 50, 0), 100) * 0.2
  );
}

function SentimentBar({ bullishPct, bearishPct }: { bullishPct: number; bearishPct: number }) {
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full">
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${bullishPct}%` }}
        transition={{ duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="bg-(--color-accent-emerald)"
      />
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${bearishPct}%` }}
        transition={{ duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="bg-(--color-accent-rose)"
      />
    </div>
  );
}

function DivergenceBadge({ divergence }: { divergence: SentimentTicker["divergence"] }) {
  if (divergence === "none") return null;
  const bullish = divergence === "bullish";
  return (
    <Tooltip
      content={
        bullish
          ? "Social sentiment is more bullish than price action suggests"
          : "Social sentiment is more bearish than price action suggests"
      }
    >
      <StatusBadge
        variant={bullish ? "success" : "warning"}
        icon={bullish ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
      >
        {bullish ? "Bullish divergence" : "Bearish divergence"}
      </StatusBadge>
    </Tooltip>
  );
}

function TickerCard({
  ticker,
  rank,
  onClick,
}: {
  ticker: SentimentTicker;
  rank: number;
  onClick: () => void;
}) {
  const reduced = useReducedMotion();
  const composite = galaxyScore(ticker);
  const divergenceColor =
    ticker.divergence === "bullish"
      ? "emerald"
      : ticker.divergence === "bearish"
      ? "amber"
      : false;

  return (
    <motion.div
      variants={rise}
      initial={reduced ? "visible" : "hidden"}
      animate="visible"
    >
      <GlassCard
        glow={divergenceColor || false}
        hoverLift
        className="cursor-pointer"
        onClick={onClick}
      >
        <div className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-(--color-border-subtle) bg-(--color-surface-glass) font-mono text-sm font-semibold text-(--color-text-primary)">
                {rank}
              </div>
              <div>
                <h3 className="font-mono text-lg font-semibold text-(--color-text-primary)">
                  {ticker.ticker}
                </h3>
                <p className="text-xs text-(--color-text-secondary)">Social score</p>
              </div>
            </div>
            <div className="flex flex-col items-end">
              <span className="text-2xl font-semibold tabular-nums text-(--color-text-primary)">
                {ticker.socialScore}
              </span>
              <DeltaChip value={ticker.priceChangePct} />
            </div>
          </div>

          <div className="mt-4 flex items-center gap-4">
            <div className="flex-1">
              <Gauge
                value={ticker.socialScore}
                size={96}
                strokeWidth={8}
                label="sentiment"
                className="!h-auto"
              />
            </div>
            <div className="flex flex-1 flex-col gap-2">
              <div className="flex items-center justify-between text-xs text-(--color-text-secondary)">
                <span className="inline-flex items-center gap-1 text-(--color-accent-emerald)">
                  <Smile className="h-3 w-3" /> {ticker.bullishPct}%
                </span>
                <span className="inline-flex items-center gap-1 text-(--color-accent-rose)">
                  <Frown className="h-3 w-3" /> {ticker.bearishPct}%
                </span>
              </div>
              <SentimentBar bullishPct={ticker.bullishPct} bearishPct={ticker.bearishPct} />
              <Sparkline
                data={ticker.socialVolume}
                color={ticker.priceChangePct >= 0 ? "emerald" : "rose"}
                height={44}
              />
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <DivergenceBadge divergence={ticker.divergence} />
              {ticker.divergence === "none" && (
                <StatusBadge variant="neutral" icon={<TrendingUp className="h-3 w-3" />}>
                  Aligned
                </StatusBadge>
              )}
            </div>
            <span className="text-[10px] text-(--color-text-tertiary)">
              Composite {composite}
            </span>
          </div>
        </div>
      </GlassCard>
    </motion.div>
  );
}

function SentimentDrawer({
  ticker,
  open,
  onClose,
}: {
  ticker: SentimentTicker | null;
  open: boolean;
  onClose: () => void;
}) {
  const history = useMemo(
    () => (ticker ? generateSentimentHistory(ticker.socialVolume) : []),
    [ticker]
  );
  const composite = ticker ? galaxyScore(ticker) : 0;
  const aiSummary = ticker
    ? ticker.divergence === "bullish"
      ? `${ticker.ticker} social sentiment is running ahead of price. Retail narratives are focused on AI/data-center tailwinds while the tape is still digesting recent volatility. Watch for a sentiment unwind if price fails to confirm.`
      : ticker.divergence === "bearish"
      ? `${ticker.ticker} social channels are more cautious than the current price suggests. Concerns around execution and competitive pressure are rising; price may be lagging the narrative shift.`
      : `${ticker.ticker} social sentiment and price action are broadly aligned. No meaningful divergence signal today, but volume is elevated relative to the trailing month.`
    : "";

  if (!ticker) return null;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center gap-3">
          <span className="font-mono text-lg font-semibold">{ticker.ticker}</span>
          <StatusBadge
            variant={ticker.divergence === "bullish" ? "success" : ticker.divergence === "bearish" ? "warning" : "neutral"}
          >
            {ticker.divergence === "none" ? "Aligned" : `${ticker.divergence} divergence`}
          </StatusBadge>
        </div>
      }
    >
      <div className="space-y-6">
        <AgentTag name="Street Ear" confidence={ticker.socialScore} />

        <div className="grid grid-cols-2 gap-3">
          <GlassCard className="p-3 text-center" hoverLift={false}>
            <p className="text-xs text-(--color-text-secondary)">Galaxy Score</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums text-(--color-accent-violet)">
              {composite}
            </p>
          </GlassCard>
          <GlassCard className="p-3 text-center" hoverLift={false}>
            <p className="text-xs text-(--color-text-secondary)">Social Score</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums text-(--color-accent-cyan)">
              {ticker.socialScore}
            </p>
          </GlassCard>
        </div>

        <GlassCard className="p-4" hoverLift={false}>
          <h4 className="mb-3 text-sm font-medium text-(--color-text-primary)">
            Sentiment over time
          </h4>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={history} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="sentiment-area" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-accent-violet)" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="var(--color-accent-violet)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--color-border-subtle)" strokeOpacity={0.5} vertical={false} />
                <XAxis dataKey="day" tick={{ fill: "var(--color-text-tertiary)", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "var(--color-text-tertiary)", fontSize: 10 }} axisLine={false} tickLine={false} domain={[0, 100]} />
                <ReTooltip
                  contentStyle={{
                    backgroundColor: "var(--color-surface-glass-hi)",
                    border: "1px solid var(--color-border-subtle)",
                    borderRadius: "12px",
                    color: "var(--color-text-primary)",
                    fontSize: 12,
                  }}
                  itemStyle={{ color: "var(--color-text-primary)" }}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="var(--color-accent-violet)"
                  strokeWidth={2}
                  fill="url(#sentiment-area)"
                  isAnimationActive={false}
                  dot={false}
                  activeDot={{ r: 4, fill: "var(--color-accent-violet)" }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        <GlassCard className="p-4" hoverLift={false}>
          <h4 className="mb-3 text-sm font-medium text-(--color-text-primary)">AI read</h4>
          <StreamingText text={aiSummary} speed={22} showScanline />
        </GlassCard>

        <GlassCard className="p-4" hoverLift={false}>
          <h4 className="mb-3 text-sm font-medium text-(--color-text-primary)">
            Top influencer posts
          </h4>
          <ul className="space-y-3">
            {ticker.topInfluencerPosts.map((post, idx) => (
              <li
                key={idx}
                className="flex gap-3 rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/40 p-3"
              >
                <MessageCircle className="mt-0.5 h-4 w-4 shrink-0 text-(--color-accent-cyan)" />
                <p className="text-sm leading-relaxed text-(--color-text-secondary)">{post}</p>
              </li>
            ))}
          </ul>
        </GlassCard>
      </div>
    </Drawer>
  );
}

export default function SentimentView() {
  const [tickers, setTickers] = useState<SentimentTicker[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<SentimentTicker | null>(null);
  const [sort, setSort] = useState<SortMode>("rank");
  const [filter, setFilter] = useState<FilterMode>("all");
  const reduced = useReducedMotion();

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSentimentTickers();
      setTickers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load sentiment");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const sortedAndFiltered = useMemo(() => {
    let list = [...tickers];
    if (filter === "bullish") list = list.filter((t) => t.bullishPct > t.bearishPct);
    if (filter === "bearish") list = list.filter((t) => t.bearishPct > t.bullishPct);

    switch (sort) {
      case "volume":
        list.sort((a, b) => b.socialVolume[b.socialVolume.length - 1].value - a.socialVolume[a.socialVolume.length - 1].value);
        break;
      case "divergence":
        list.sort((a, b) => {
          const aDiv = a.divergence === "none" ? 0 : a.divergence === "bullish" ? 2 : 1;
          const bDiv = b.divergence === "none" ? 0 : b.divergence === "bullish" ? 2 : 1;
          return bDiv - aDiv;
        });
        break;
      default:
        list.sort((a, b) => b.socialScore - a.socialScore);
    }
    return list;
  }, [tickers, sort, filter]);

  const divergences = useMemo(
    () => tickers.filter((t) => t.divergence !== "none").slice(0, 3),
    [tickers]
  );

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-9 w-32" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-7xl">
        <EmptyState
          title="Couldn't load sentiment"
          description={error}
          icon={<RefreshCw className="h-6 w-6" />}
          action={{ label: "Retry", onClick: load }}
        />
      </div>
    );
  }

  return (
    <motion.div
      variants={stagger}
      initial={reduced ? "visible" : "hidden"}
      animate="visible"
      className="mx-auto max-w-7xl space-y-6"
    >
      {/* Header */}
      <motion.div variants={rise} className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold text-(--color-text-primary)">Sentiment</h1>
            <MockDataBadge />
          </div>
          <p className="text-sm text-(--color-text-secondary)">
            Trending social signals ranked by LunarCrush social score
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Tooltip content="Fixture data shaped like the LunarCrush feed.">
            <StatusBadge variant="info" icon={<Brain className="h-3 w-3" />}>
              LunarCrush shape
            </StatusBadge>
          </Tooltip>
        </div>
      </motion.div>

      {/* Divergence highlights */}
      {divergences.length > 0 && (
        <motion.div variants={rise}>
          <GlassCard className="p-4" glow="violet" hoverLift={false}>
            <div className="flex items-center gap-2 mb-3">
              <Activity className="h-4 w-4 text-(--color-accent-violet)" />
              <h2 className="text-sm font-semibold text-(--color-text-primary)">
                Divergence highlights
              </h2>
            </div>
            <div className="flex flex-wrap gap-2">
              {divergences.map((t) => (
                <GlassButton
                  key={t.ticker}
                  variant="ghost"
                  onClick={() => setSelectedTicker(t)}
                  leftIcon={
                    t.divergence === "bullish" ? (
                      <ArrowUpRight className="h-3.5 w-3.5 text-(--color-accent-emerald)" />
                    ) : (
                      <ArrowDownRight className="h-3.5 w-3.5 text-(--color-accent-amber)" />
                    )
                  }
                >
                  <span className="font-mono">{t.ticker}</span>
                  <span className="text-(--color-text-secondary)">
                    {formatPercent(t.priceChangePct)}
                  </span>
                </GlassButton>
              ))}
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Controls */}
      <motion.div variants={rise} className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SegmentedControl
          options={[
            { value: "rank", label: "Rank" },
            { value: "volume", label: "Volume" },
            { value: "divergence", label: "Divergence" },
          ]}
          value={sort}
          onChange={(v) => setSort(v as SortMode)}
        />
        <SegmentedControl
          options={[
            { value: "all", label: "All" },
            { value: "bullish", label: "Bullish" },
            { value: "bearish", label: "Bearish" },
          ]}
          value={filter}
          onChange={(v) => setFilter(v as FilterMode)}
        />
      </motion.div>

      {/* Grid */}
      {sortedAndFiltered.length === 0 ? (
        <motion.div variants={fade}>
          <EmptyState
            title="No tickers match"
            description="Try changing the sort or filter."
            icon={<TrendingUp className="h-6 w-6" />}
            action={{ label: "Reset filters", onClick: () => { setSort("rank"); setFilter("all"); } }}
          />
        </motion.div>
      ) : (
        <motion.div
          variants={stagger}
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          {sortedAndFiltered.map((ticker, idx) => (
            <TickerCard
              key={ticker.ticker}
              ticker={ticker}
              rank={idx + 1}
              onClick={() => setSelectedTicker(ticker)}
            />
          ))}
        </motion.div>
      )}

      <SentimentDrawer
        ticker={selectedTicker}
        open={!!selectedTicker}
        onClose={() => setSelectedTicker(null)}
      />
    </motion.div>
  );
}
