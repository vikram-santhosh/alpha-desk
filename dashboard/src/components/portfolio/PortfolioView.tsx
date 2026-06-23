import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  Treemap,
} from "recharts";
import { Wallet } from "lucide-react";
import type { PortfolioSummary, SleevePosition } from "@/types";
import { askAlphaDesk, fetchPortfolioSummary, fetchPositions } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { cn } from "@/lib/cn";
import { rise, stagger } from "@/lib/motion";
import { AgentTag } from "@/components/ui/AgentTag";
import { DeltaChip } from "@/components/ui/DeltaChip";
import { Drawer } from "@/components/ui/Drawer";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlassButton } from "@/components/ui/GlassButton";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sparkline } from "@/components/ui/Sparkline";
import { StatCard } from "@/components/ui/StatCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StreamingText } from "@/components/ui/StreamingText";

type Timeframe = "1D" | "1W" | "1M" | "YTD";
type ChartMode = "donut" | "treemap";

interface AllocationDatum {
  name: string;
  ticker: string;
  value: number;
  weight: number;
  color: string;
  index: number;
  [key: string]: unknown;
}

const TIMEFRAME_OPTIONS: { value: Timeframe; label: string }[] = [
  { value: "1D", label: "1D" },
  { value: "1W", label: "1W" },
  { value: "1M", label: "1M" },
  { value: "YTD", label: "YTD" },
];

const CHART_OPTIONS: { value: ChartMode; label: string }[] = [
  { value: "donut", label: "Donut" },
  { value: "treemap", label: "Treemap" },
];

const CHART_COLORS = [
  "var(--color-accent-cyan)",
  "var(--color-accent-violet)",
  "var(--color-accent-emerald)",
  "var(--color-accent-amber)",
  "var(--color-accent-rose)",
  "var(--color-accent-blue)",
  "oklch(0.72 0.13 320)",
  "oklch(0.75 0.12 150)",
  "oklch(0.68 0.12 40)",
];

function getBreachVariant(
  breach: SleevePosition["breach"]
): StatusBadgeVariant | undefined {
  if (breach === "critical") return "critical";
  if (breach === "warning") return "warning";
  if (breach === "info") return "info";
  return undefined;
}

type StatusBadgeVariant = "info" | "success" | "warning" | "critical" | "neutral";

function getBreachLabel(breach: SleevePosition["breach"]): string {
  if (breach === "critical") return "Critical";
  if (breach === "warning") return "Warning";
  if (breach === "info") return "Info";
  return "OK";
}

export default function PortfolioView() {
  const [positions, setPositions] = useState<SleevePosition[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");
  const [chartMode, setChartMode] = useState<ChartMode>("donut");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [commentary, setCommentary] = useState<{
    text: string;
    agent: string;
    confidence: number;
  } | null>(null);
  const [commentaryLoading, setCommentaryLoading] = useState(false);
  const reducedMotion = useReducedMotion();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pos, sum] = await Promise.all([
        fetchPositions(),
        fetchPortfolioSummary(),
      ]);
      setPositions(pos);
      setSummary(sum);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load portfolio data"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedPosition = useMemo(
    () => positions.find((p) => p.ticker === selectedTicker) ?? null,
    [positions, selectedTicker]
  );

  const allocationData: AllocationDatum[] = useMemo(
    () =>
      positions.map((p, index) => ({
        name: p.name,
        ticker: p.ticker,
        value: p.value,
        weight: p.weight,
        color: CHART_COLORS[index % CHART_COLORS.length],
        index,
      })),
    [positions]
  );

  const breaches = useMemo(
    () => positions.filter((p) => p.breach),
    [positions]
  );

  const handleGenerateCommentary = useCallback(async () => {
    if (commentaryLoading) return;
    setCommentaryLoading(true);
    setCommentary(null);
    try {
      const result = await askAlphaDesk(
        "Generate portfolio commentary on concentration, sector risk, and key exposures."
      );
      setCommentary({
        text: result.answer,
        agent: result.agent,
        confidence: result.confidence,
      });
    } catch {
      setCommentary({
        text: "Unable to generate commentary right now. Please try again.",
        agent: "Advisor",
        confidence: 0,
      });
    } finally {
      setCommentaryLoading(false);
    }
  }, [commentaryLoading]);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-10 w-72" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <div className="grid gap-6 lg:grid-cols-3">
          <Skeleton className="h-96 lg:col-span-1" />
          <Skeleton className="h-96 lg:col-span-2" />
        </div>
      </div>
    );
  }

  if (error || !summary) {
    return (
      <EmptyState
        title="Could not load portfolio"
        description={error ?? "Data unavailable"}
        icon={<Wallet className="h-6 w-6" />}
        action={{ label: "Retry", onClick: load }}
      />
    );
  }

  return (
    <motion.div
      initial={reducedMotion ? false : "hidden"}
      animate="visible"
      variants={stagger}
      className="space-y-6"
    >
      {/* Header */}
      <motion.div
        variants={rise}
        className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"
      >
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">
            Portfolio
          </h1>
          <p className="text-sm text-(--color-text-secondary)">
            Sleeve allocation, holdings, and risk commentary
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <SegmentedControl
            options={TIMEFRAME_OPTIONS}
            value={timeframe}
            onChange={setTimeframe}
            layoutId="portfolio-timeframe"
          />
          <GlassButton
            sparkle
            onClick={handleGenerateCommentary}
            disabled={commentaryLoading}
          >
            {commentaryLoading ? "Generating…" : "Generate portfolio commentary"}
          </GlassButton>
        </div>
      </motion.div>

      {/* Stats */}
      <motion.div
        variants={rise}
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5"
      >
        <StatCard
          label="Portfolio Value"
          value={summary.totalValue}
          formatter={(v) => formatCurrency(v)}
          delta={summary.dayPnlPct}
        />
        <StatCard
          label="Day P&L"
          value={summary.dayPnl}
          formatter={(v) => formatCurrency(v)}
          delta={summary.dayPnlPct}
        />
        <GlassCard className="p-4" hoverLift={false}>
          <p className="text-xs font-medium text-(--color-text-secondary) uppercase tracking-wide">
            Open Breaches
          </p>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span
              className={cn(
                "text-3xl font-semibold tracking-tight font-mono tabular-nums",
                breaches.length > 0
                  ? "text-(--color-accent-rose)"
                  : "text-(--color-accent-emerald)"
              )}
            >
              {breaches.length}
            </span>
            {breaches.length > 0 ? (
              <StatusBadge variant="critical" pulse>
                {breaches.length} active
              </StatusBadge>
            ) : (
              <StatusBadge variant="success">All clear</StatusBadge>
            )}
          </div>
        </GlassCard>
        <StatCard
          label="Active Signals"
          value={summary.activeSignalCount}
          formatter={(v) => v.toLocaleString()}
        />
        <StatCard
          label="Cash (SGOV)"
          value={summary.cash}
          formatter={(v) => formatCurrency(v)}
        />
      </motion.div>

      {/* AI Commentary */}
      <AnimatePresence>
        {commentary && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: reducedMotion ? 0 : 0.3 }}
          >
            <GlassCard glow="violet" className="p-4">
              <div className="flex flex-wrap items-center gap-3 mb-3">
                <AgentTag
                  name={commentary.agent}
                  confidence={commentary.confidence}
                />
                <span className="text-xs text-(--color-text-secondary)">
                  Portfolio commentary
                </span>
              </div>
              <StreamingText text={commentary.text} speed={24} showScanline />
            </GlassCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Allocation + Holdings */}
      <motion.div
        variants={rise}
        className="grid gap-6 lg:grid-cols-3"
      >
        {/* Allocation Chart */}
        <GlassCard className="p-5 lg:col-span-1">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-(--color-text-primary)">
              Allocation
            </h2>
            <SegmentedControl
              options={CHART_OPTIONS}
              value={chartMode}
              onChange={setChartMode}
              layoutId="portfolio-chart-mode"
            />
          </div>
          <div className="relative h-72">
            <ResponsiveContainer width="100%" height="100%">
              {chartMode === "donut" ? (
                <PieChart>
                  <Pie
                    data={allocationData}
                    dataKey="value"
                    nameKey="ticker"
                    innerRadius="60%"
                    outerRadius="90%"
                    paddingAngle={2}
                    stroke="none"
                    isAnimationActive={!reducedMotion}
                  >
                    {allocationData.map((entry) => (
                      <Cell key={entry.ticker} fill={entry.color} />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    formatter={(value, _name, props: unknown) => {
                      const p = props as { payload?: AllocationDatum } | undefined;
                      const d = p?.payload;
                      return [
                        formatCurrency(Number(value)),
                        `${d?.ticker} (${formatPercent(
                          (d?.weight ?? 0) * 100,
                          false
                        )})`,
                      ];
                    }}
                    contentStyle={{
                      background: "var(--color-surface-glass-hi)",
                      border: "1px solid var(--color-border-subtle)",
                      borderRadius: "12px",
                      backdropFilter: "blur(12px)",
                    }}
                    itemStyle={{ color: "var(--color-text-primary)" }}
                  />
                </PieChart>
              ) : (
                <Treemap
                  data={allocationData}
                  dataKey="value"
                  nameKey="ticker"
                  aspectRatio={4 / 3}
                  stroke="var(--color-border-subtle)"
                  colorPanel={CHART_COLORS}
                  isAnimationActive={!reducedMotion}
                >
                  <RechartsTooltip
                    formatter={(value, _name, props: unknown) => {
                      const p = props as { payload?: AllocationDatum } | undefined;
                      const d = p?.payload;
                      return [
                        formatCurrency(Number(value)),
                        `${d?.ticker} (${formatPercent(
                          (d?.weight ?? 0) * 100,
                          false
                        )})`,
                      ];
                    }}
                    contentStyle={{
                      background: "var(--color-surface-glass-hi)",
                      border: "1px solid var(--color-border-subtle)",
                      borderRadius: "12px",
                      backdropFilter: "blur(12px)",
                    }}
                    itemStyle={{ color: "var(--color-text-primary)" }}
                  />
                </Treemap>
              )}
            </ResponsiveContainer>
            {chartMode === "donut" && (
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-xs text-(--color-text-secondary)">
                  Total Value
                </span>
                <span className="text-xl font-semibold tabular-nums text-(--color-text-primary)">
                  {formatCurrency(summary.totalValue)}
                </span>
              </div>
            )}
          </div>

          {/* Legend */}
          <div className="mt-4 grid grid-cols-2 gap-2">
            {allocationData.map((d) => (
              <div key={d.ticker} className="flex items-center gap-2">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: d.color }}
                />
                <span className="text-xs text-(--color-text-secondary) truncate">
                  {d.ticker}
                </span>
                <span className="ml-auto text-xs tabular-nums text-(--color-text-primary)">
                  {formatPercent(d.weight * 100, false)}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Holdings Table */}
        <GlassCard className="p-0 lg:col-span-2">
          <div className="border-b border-(--color-border-subtle) px-5 py-4">
            <h2 className="text-sm font-semibold text-(--color-text-primary)">
              Holdings
            </h2>
          </div>
          {positions.length === 0 ? (
            <EmptyState
              title="No holdings"
              description="There are no positions to display."
              icon={<Wallet className="h-6 w-6" />}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-(--color-border-subtle) text-xs uppercase tracking-wide text-(--color-text-secondary)">
                    <th className="px-5 py-3 font-medium">Ticker</th>
                    <th className="px-5 py-3 font-medium">Name</th>
                    <th className="px-5 py-3 font-medium text-right">Weight</th>
                    <th className="px-5 py-3 font-medium text-right">Price</th>
                    <th className="px-5 py-3 font-medium text-right">Day Δ</th>
                    <th className="px-5 py-3 font-medium text-right">
                      Position Value
                    </th>
                    <th className="px-5 py-3 font-medium">30D</th>
                    <th className="px-5 py-3 font-medium text-center">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr
                      key={p.ticker}
                      onClick={() => setSelectedTicker(p.ticker)}
                      className="cursor-pointer border-b border-(--color-border-subtle) transition-colors last:border-b-0 hover:bg-(--color-surface-glass-hi)"
                    >
                      <td className="px-5 py-3 font-mono font-medium text-(--color-text-primary)">
                        {p.ticker}
                      </td>
                      <td className="px-5 py-3 text-(--color-text-secondary)">
                        {p.name}
                      </td>
                      <td className="px-5 py-3 text-right tabular-nums text-(--color-text-primary)">
                        {formatPercent(p.weight * 100, false)}
                      </td>
                      <td className="px-5 py-3 text-right tabular-nums text-(--color-text-primary)">
                        {formatCurrency(p.price)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <DeltaChip value={p.changePct} />
                      </td>
                      <td className="px-5 py-3 text-right tabular-nums text-(--color-text-primary)">
                        {formatCurrency(p.value)}
                      </td>
                      <td className="px-5 py-3">
                        <div className="w-24">
                          <Sparkline
                            data={p.sparkline}
                            color={p.changePct >= 0 ? "emerald" : "rose"}
                            height={32}
                          />
                        </div>
                      </td>
                      <td className="px-5 py-3 text-center">
                        {p.breach ? (
                          <StatusBadge
                            variant={getBreachVariant(p.breach)}
                            pulse={p.breach === "critical"}
                          >
                            {getBreachLabel(p.breach)}
                          </StatusBadge>
                        ) : (
                          <StatusBadge variant="success">OK</StatusBadge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      </motion.div>

      {/* Detail Drawer */}
      <Drawer
        open={!!selectedPosition}
        onClose={() => setSelectedTicker(null)}
        title={
          selectedPosition
            ? `${selectedPosition.ticker} — ${selectedPosition.name}`
            : undefined
        }
      >
        {selectedPosition && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-(--color-text-secondary)">
                  Position Value
                </p>
                <p className="text-2xl font-semibold tabular-nums text-(--color-text-primary)">
                  {formatCurrency(selectedPosition.value)}
                </p>
              </div>
              <DeltaChip value={selectedPosition.changePct} />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 p-3">
                <p className="text-xs text-(--color-text-secondary)">Weight</p>
                <p className="text-base font-medium tabular-nums text-(--color-text-primary)">
                  {formatPercent(selectedPosition.weight * 100, false)}
                </p>
              </div>
              <div className="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 p-3">
                <p className="text-xs text-(--color-text-secondary)">Shares</p>
                <p className="text-base font-medium tabular-nums text-(--color-text-primary)">
                  {selectedPosition.shares.toLocaleString()}
                </p>
              </div>
              <div className="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 p-3">
                <p className="text-xs text-(--color-text-secondary)">Price</p>
                <p className="text-base font-medium tabular-nums text-(--color-text-primary)">
                  {formatCurrency(selectedPosition.price)}
                </p>
              </div>
              <div className="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 p-3">
                <p className="text-xs text-(--color-text-secondary)">Theme</p>
                <p className="text-base font-medium text-(--color-text-primary)">
                  {selectedPosition.theme}
                </p>
              </div>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold text-(--color-text-primary)">
                Thesis
              </h3>
              <p className="text-sm leading-relaxed text-(--color-text-secondary)">
                {selectedPosition.thesis ?? "No thesis recorded."}
              </p>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold text-(--color-text-primary)">
                Agent Notes
              </h3>
              <GlassCard className="p-3" hoverLift={false}>
                <div className="flex items-center gap-2 mb-2">
                  <AgentTag name="Portfolio Analyst" confidence={72} />
                </div>
                <p className="text-sm text-(--color-text-secondary)">
                  Thesis status is{" "}
                  <strong className="text-(--color-text-primary)">
                    {selectedPosition.thesisStatus?.replace("_", " ")}
                  </strong>
                  .{" "}
                  {selectedPosition.breach
                    ? `Position is flagged with a ${selectedPosition.breach} breach. Review sizing versus conviction.`
                    : "Position is within expected risk thresholds."}
                </p>
              </GlassCard>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold text-(--color-text-primary)">
                Breach Thresholds
              </h3>
              <div className="space-y-2">
                <ThresholdRow
                  label="Max position weight"
                  current={selectedPosition.weight}
                  limit={0.2}
                  formatter={(v) => formatPercent(v * 100, false)}
                />
                <ThresholdRow
                  label="Daily drawdown"
                  current={Math.abs(Math.min(selectedPosition.changePct, 0))}
                  limit={5}
                  formatter={(v) => formatPercent(v, false)}
                />
              </div>
            </div>
          </div>
        )}
      </Drawer>
    </motion.div>
  );
}

interface ThresholdRowProps {
  label: string;
  current: number;
  limit: number;
  formatter: (v: number) => string;
}

function ThresholdRow({ label, current, limit, formatter }: ThresholdRowProps) {
  const pct = Math.min((current / limit) * 100, 100);
  const breached = current > limit;
  return (
    <div className="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 p-3">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="text-(--color-text-secondary)">{label}</span>
        <span
          className={cn(
            "tabular-nums",
            breached
              ? "text-(--color-accent-rose)"
              : "text-(--color-text-primary)"
          )}
        >
          {formatter(current)} / {formatter(limit)}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            breached ? "bg-(--color-accent-rose)" : "bg-(--color-accent-emerald)"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
