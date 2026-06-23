import { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  FlaskConical,
  Globe,
  Radio,
  Rocket,
  Sparkles,
  TrendingUp,
} from "lucide-react";

import { AgentTag } from "@/components/ui/AgentTag";
import { DeltaChip } from "@/components/ui/DeltaChip";
import { EmptyState } from "@/components/ui/EmptyState";
import { Gauge } from "@/components/ui/Gauge";
import { GlassButton } from "@/components/ui/GlassButton";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassInput } from "@/components/ui/GlassInput";
import { MockDataBadge } from "@/components/ui/MockDataBadge";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sparkline } from "@/components/ui/Sparkline";
import { StatCard } from "@/components/ui/StatCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StreamingText } from "@/components/ui/StreamingText";

import { askAlphaDesk, fetchDailyBrief, fetchPortfolioSummary } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatCurrency, formatDateTime, formatPercent } from "@/lib/format";
import { rise, stagger } from "@/lib/motion";
import type {
  Alert,
  DailyBriefSection,
  MacroRegime,
  Moonshot,
  PortfolioSummary,
  ResearchReport,
  SentimentTicker,
  SleevePosition,
} from "@/types";

interface CommandCenterProps {
  onNavigate?: (to: string) => void;
}

function StreamingLine({
  text,
  className,
  speed = 22,
}: {
  text: string;
  className?: string;
  speed?: number;
}) {
  const reduced = useReducedMotion();
  if (reduced) {
    return (
      <p
        className={cn(
          "text-sm leading-relaxed text-(--color-text-primary)",
          className
        )}
      >
        {text}
      </p>
    );
  }
  return (
    <StreamingText
      text={text}
      showScanline
      speed={speed}
      className={className}
    />
  );
}

function SectionHeader({
  icon: Icon,
  title,
  action,
}: {
  icon: React.ElementType;
  title: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2.5">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-(--color-border-subtle) bg-(--color-surface-elevated) text-(--color-text-secondary)">
          <Icon className="h-4 w-4" />
        </div>
        <h3 className="text-sm font-semibold text-(--color-text-primary)">
          {title}
        </h3>
      </div>
      {action}
    </div>
  );
}

function MiniSparkline({
  data,
  positive,
}: {
  data: SleevePosition["sparkline"];
  positive: boolean;
}) {
  return (
    <Sparkline
      data={data}
      color={positive ? "emerald" : "rose"}
      height={32}
      className="w-16"
    />
  );
}

function SentimentBar({
  bullishPct,
  bearishPct,
}: {
  bullishPct: number;
  bearishPct: number;
}) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
      <div className="flex h-full w-full">
        <div
          className="h-full bg-(--color-accent-emerald)"
          style={{ width: `${bullishPct}%` }}
        />
        <div
          className="h-full bg-(--color-accent-rose)"
          style={{ width: `${bearishPct}%` }}
        />
      </div>
    </div>
  );
}

function ConvictionMeter({ value }: { value: number }) {
  const clamped = Math.min(Math.max(value, 0), 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-(--color-surface-elevated)">
        <div
          className="h-full rounded-full bg-(--color-accent-violet) transition-all duration-700"
          style={{ width: `${clamped}%` }}
        />
      </div>
      <span className="text-[10px] tabular-nums text-(--color-text-secondary)">
        {clamped}%
      </span>
    </div>
  );
}

function BreachesSection({
  section,
  onNavigate,
}: {
  section: DailyBriefSection;
  onNavigate?: CommandCenterProps["onNavigate"];
}) {
  const alerts = section.content as Alert[];
  const summary = useMemo(() => {
    const names = alerts.map((a) => `${a.ticker} ${a.metric.toLowerCase()}`);
    return `${alerts.length} active breach${alerts.length === 1 ? "" : "es"} require${alerts.length === 1 ? "s" : ""} attention: ${names.join(", ")}.`;
  }, [alerts]);

  return (
    <GlassCard glow="rose" className="p-4">
      <SectionHeader
        icon={AlertTriangle}
        title={section.title}
        action={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <MockDataBadge />
            <GlassButton
              variant="ghost"
              rightIcon={<ArrowRight className="h-3.5 w-3.5" />}
              onClick={() => onNavigate?.("/alerts")}
            >
              View alerts
            </GlassButton>
          </div>
        }
      />
      <StreamingLine text={summary} className="mb-4" />
      <div className="flex flex-wrap gap-2">
        {alerts.map((alert) => (
          <StatusBadge
            key={alert.id}
            variant={alert.severity === "critical" ? "critical" : "warning"}
            pulse={alert.state === "new"}
          >
            <span className="font-mono">{alert.ticker}</span>
            <span className="opacity-75">{alert.metric}</span>
          </StatusBadge>
        ))}
      </div>
    </GlassCard>
  );
}

function MoversSection({ section }: { section: DailyBriefSection }) {
  const movers = section.content as SleevePosition[];
  const summary = useMemo(() => {
    const top = movers
      .slice(0, 4)
      .map((m) => `${m.ticker} ${formatPercent(m.changePct)}`)
      .join(", ");
    return `Top movers today: ${top}.`;
  }, [movers]);

  return (
    <GlassCard className="p-4">
      <SectionHeader icon={TrendingUp} title={section.title} action={<MockDataBadge />} />
      <StreamingLine text={summary} className="mb-4" />
      <div className="grid gap-3 sm:grid-cols-2">
        {movers.map((pos) => (
          <div
            key={pos.ticker}
            className="flex items-center justify-between gap-3 rounded-xl border border-(--color-border-subtle) bg-(--color-surface-glass)/50 px-3 py-2.5"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-(--color-text-primary)">
                  {pos.ticker}
                </span>
                <DeltaChip value={pos.changePct} />
              </div>
              <p className="truncate text-xs text-(--color-text-secondary)">
                {pos.name}
              </p>
            </div>
            <MiniSparkline data={pos.sparkline} positive={pos.changePct >= 0} />
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

function MacroSection({ section }: { section: DailyBriefSection }) {
  const regime = section.content as MacroRegime;
  return (
    <GlassCard className="p-4">
      <SectionHeader icon={Globe} title={section.title} />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <div className="flex-1">
          <p className="text-lg font-semibold text-(--color-text-primary)">
            {regime.call}
          </p>
          <div className="mt-3">
            <AgentTag name={regime.agent} confidence={regime.confidence} />
          </div>
          <div className="mt-3">
            <StatusBadge
              variant={
                regime.source === "backend" && !regime.degradedReasons?.length
                  ? "success"
                  : "warning"
              }
            >
              {regime.source === "backend" ? "Backend macro" : "Mock macro"}
            </StatusBadge>
          </div>
          <p className="mt-2 text-xs text-(--color-text-tertiary)">
            Scanned {formatDateTime(regime.scannedAt)}
          </p>
          <div className="mt-4">
            <StreamingLine text={regime.rationale} />
          </div>
        </div>
        <div className="flex shrink-0 justify-center">
          <Gauge
            value={regime.score}
            size={140}
            strokeWidth={10}
            label="Risk-On"
          />
        </div>
      </div>
    </GlassCard>
  );
}

function SentimentSection({ section }: { section: DailyBriefSection }) {
  const tickers = section.content as SentimentTicker[];
  const summary = useMemo(() => {
    const items = tickers.map((t) => `${t.ticker} (${t.divergence})`);
    return `Social sentiment diverges from price on ${items.join(", ")}.`;
  }, [tickers]);

  return (
    <GlassCard className="p-4">
      <SectionHeader icon={Radio} title={section.title} action={<MockDataBadge />} />
      <StreamingLine text={summary} className="mb-4" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {tickers.map((t) => (
          <div
            key={t.ticker}
            className="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-glass)/50 p-3"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="font-mono text-sm font-semibold text-(--color-text-primary)">
                {t.ticker}
              </span>
              <StatusBadge
                variant={
                  t.divergence === "bullish"
                    ? "success"
                    : t.divergence === "bearish"
                      ? "critical"
                      : "neutral"
                }
              >
                {t.divergence}
              </StatusBadge>
            </div>
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs text-(--color-text-secondary)">
                Social score
              </span>
              <span className="ml-auto text-xs font-medium tabular-nums text-(--color-text-primary)">
                {t.socialScore}
              </span>
            </div>
            <ConvictionMeter value={t.socialScore} />
            <div className="mt-3">
              <Sparkline
                data={t.socialVolume}
                color="violet"
                height={28}
                className="w-full"
              />
            </div>
            <div className="mt-3">
              <div className="mb-1 flex justify-between text-[10px] text-(--color-text-tertiary)">
                <span>Bullish {t.bullishPct}%</span>
                <span>Bearish {t.bearishPct}%</span>
              </div>
              <SentimentBar
                bullishPct={t.bullishPct}
                bearishPct={t.bearishPct}
              />
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

function ResearchSection({ section }: { section: DailyBriefSection }) {
  const report = section.content as ResearchReport;
  const [showSummary, setShowSummary] = useState(false);

  return (
    <GlassCard className="p-4">
      <SectionHeader icon={FlaskConical} title={section.title} action={<MockDataBadge />} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {report.tickers.map((ticker) => (
          <span
            key={ticker}
            className="rounded-md bg-(--color-surface-elevated) px-2 py-0.5 font-mono text-xs text-(--color-text-primary)"
          >
            {ticker}
          </span>
        ))}
        <StatusBadge variant="info">{report.tier}</StatusBadge>
      </div>
      <h4 className="text-base font-semibold text-(--color-text-primary)">
        {report.title}
      </h4>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <AgentTag name={report.agent} confidence={report.confidence} />
        <span className="text-xs text-(--color-text-tertiary)">
          {report.freshness}
        </span>
      </div>
      {!showSummary ? (
        <GlassButton
          variant="ghost"
          sparkle
          className="mt-4"
          onClick={() => setShowSummary(true)}
        >
          Summarize
        </GlassButton>
      ) : (
        <div className="mt-4 rounded-xl border border-(--color-border-subtle) bg-(--color-surface-glass)/50 p-3">
          <StreamingLine text={report.summary} />
        </div>
      )}
    </GlassCard>
  );
}

function MoonshotSection({ section }: { section: DailyBriefSection }) {
  const moonshot = section.content as Moonshot;
  const total = moonshot.asymmetry.downside + moonshot.asymmetry.upside;
  const upsidePct = total > 0 ? (moonshot.asymmetry.upside / total) * 100 : 50;

  return (
    <GlassCard className="p-4">
      <SectionHeader icon={Rocket} title={section.title} />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-base font-semibold text-(--color-text-primary)">
              {moonshot.ticker}
            </span>
            <span className="text-sm text-(--color-text-secondary)">
              {moonshot.name}
            </span>
            <StatusBadge variant="info">{moonshot.sector}</StatusBadge>
            <StatusBadge variant={moonshot.source === "backend" ? "success" : "warning"}>
              {moonshot.source === "backend" ? "Backend" : "Mock"}
            </StatusBadge>
          </div>
          <div className="mt-3">
            <ConvictionMeter value={moonshot.conviction} />
          </div>
          <div className="mt-4">
            <StreamingLine text={moonshot.whyNow} />
          </div>
          {moonshot.sourceDetail && (
            <p className="mt-2 text-xs text-(--color-text-tertiary)">
              {moonshot.sourceDetail}
            </p>
          )}
        </div>
        <div className="w-full sm:w-40">
          <div className="mb-1 flex justify-between text-xs text-(--color-text-secondary)">
            <span>Asymmetry</span>
            <span className="tabular-nums">
              {moonshot.asymmetry.upside}:{moonshot.asymmetry.downside}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
            <div className="flex h-full w-full">
              <div
                className="h-full bg-(--color-accent-rose)"
                style={{ width: `${100 - upsidePct}%` }}
              />
              <div
                className="h-full bg-(--color-accent-emerald)"
                style={{ width: `${upsidePct}%` }}
              />
            </div>
          </div>
          <p className="mt-1 text-[10px] text-(--color-text-tertiary)">
            High-risk / high-reward
          </p>
        </div>
      </div>
    </GlassCard>
  );
}

function BriefSectionCard({
  section,
  onNavigate,
}: {
  section: DailyBriefSection;
  onNavigate?: CommandCenterProps["onNavigate"];
}) {
  switch (section.type) {
    case "breaches":
      return <BreachesSection section={section} onNavigate={onNavigate} />;
    case "movers":
      return <MoversSection section={section} />;
    case "macro":
      return <MacroSection section={section} />;
    case "sentiment":
      return <SentimentSection section={section} />;
    case "research":
      return <ResearchSection section={section} />;
    case "moonshot":
      return <MoonshotSection section={section} />;
    default:
      return null;
  }
}

export default function CommandCenter({
  onNavigate,
}: CommandCenterProps) {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [brief, setBrief] = useState<DailyBriefSection[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{
    text: string;
    agent: string;
    confidence: number;
  } | null>(null);
  const [asking, setAsking] = useState(false);

  const reduced = useReducedMotion();

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, b] = await Promise.all([
        fetchPortfolioSummary(),
        fetchDailyBrief(),
      ]);
      setSummary(s);
      setBrief(b);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load command center");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || asking) return;
    setAsking(true);
    setAnswer(null);
    try {
      const result = await askAlphaDesk(question.trim());
      setAnswer({
        text: result.answer,
        agent: result.agent,
        confidence: result.confidence,
      });
    } catch (e) {
      setAnswer({
        text: e instanceof Error ? e.message : "Unable to reach AlphaDesk.",
        agent: "System",
        confidence: 0,
      });
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      {/* Ask AlphaDesk */}
      <section className="space-y-3">
        <div className="flex justify-end">
          <MockDataBadge label="Mock AI answer" />
        </div>
        <form
          onSubmit={handleAsk}
          className={cn(
            "group relative flex items-center gap-3 rounded-2xl border border-(--color-border-subtle)",
            "bg-(--color-surface-glass) backdrop-blur-xl px-4 py-3 shadow-[var(--shadow-glass)]",
            "transition-all duration-200",
            "focus-within:border-(--color-accent-violet)/50 focus-within:shadow-[0_0_28px_var(--color-glow-violet)]"
          )}
        >
          <Sparkles className="h-5 w-5 shrink-0 text-(--color-accent-violet)" />
          <GlassInput
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask AlphaDesk anything…"
            className="border-0 bg-transparent px-0 py-0 shadow-none placeholder:text-(--color-text-tertiary) focus:ring-0"
          />
          <GlassButton
            type="submit"
            variant="solid"
            disabled={asking || !question.trim()}
            className="hidden sm:inline-flex"
          >
            Ask
          </GlassButton>
        </form>

        {asking && (
          <div className="flex items-center gap-2 text-xs text-(--color-text-secondary)">
            <Bot className="h-3.5 w-3.5 text-(--color-accent-violet)" />
            <span>AlphaDesk is thinking…</span>
          </div>
        )}

        {answer && !asking && (
          <GlassCard glow="violet" className="p-4">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <AgentTag name={answer.agent} confidence={answer.confidence} />
            </div>
            {reduced ? (
              <p className="text-sm leading-relaxed text-(--color-text-primary)">
                {answer.text}
              </p>
            ) : (
              <StreamingText text={answer.text} showScanline speed={24} />
            )}
          </GlassCard>
        )}
      </section>

      {/* Stat row */}
      {summary && (
        <div className="flex justify-end">
          <MockDataBadge label="Mock portfolio summary" />
        </div>
      )}
      {loading && !summary ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : summary ? (
        <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          <StatCard
            label="Portfolio Value"
            value={summary.totalValue}
            formatter={(v) => formatCurrency(v, true)}
          />
          <StatCard
            label="Day P&L"
            value={summary.dayPnl}
            delta={summary.dayPnlPct}
            formatter={(v) => formatCurrency(v, true)}
          />
          <StatCard
            label="Open Breaches"
            value={summary.activeBreachCount}
            formatter={(v) => `${Math.round(v)}`}
          />
          <StatCard
            label="Active Signals"
            value={summary.activeSignalCount}
            formatter={(v) => `${Math.round(v)}`}
          />
          <StatCard
            label="Cash (SGOV)"
            value={summary.cash}
            formatter={(v) => formatCurrency(v, true)}
          />
        </section>
      ) : null}

      {/* Morning Brief */}
      <section>
        <div className="mb-4 flex items-center gap-2">
          <Activity className="h-4 w-4 text-(--color-accent-cyan)" />
          <h2 className="text-base font-semibold text-(--color-text-primary)">
            Morning Brief
          </h2>
          {summary?.asOf && (
            <span className="ml-auto text-xs text-(--color-text-tertiary)">
              As of {formatDateTime(summary.asOf)}
            </span>
          )}
        </div>

        {loading && !brief ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-40" />
            ))}
          </div>
        ) : error ? (
          <EmptyState
            title="Brief unavailable"
            description={error}
            action={{ label: "Retry", onClick: load }}
          />
        ) : brief && brief.length > 0 ? (
          <motion.div
            className="space-y-3"
            initial="hidden"
            animate="visible"
            variants={stagger}
          >
            {brief.map((section) => (
              <motion.div key={section.type} variants={rise}>
                <BriefSectionCard section={section} onNavigate={onNavigate} />
              </motion.div>
            ))}
          </motion.div>
        ) : (
          <EmptyState
            title="No brief items"
            description="Nothing to report right now."
          />
        )}
      </section>
    </div>
  );
}
