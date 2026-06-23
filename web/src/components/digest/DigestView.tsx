import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { Calendar, Check, Copy, Mail, RefreshCw } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassButton } from "@/components/ui/GlassButton";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { DeltaChip } from "@/components/ui/DeltaChip";
import { Sparkline } from "@/components/ui/Sparkline";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { MockDataBadge } from "@/components/ui/MockDataBadge";
import { Gauge } from "@/components/ui/Gauge";
import { AgentTag } from "@/components/ui/AgentTag";
import { GlassInput } from "@/components/ui/GlassInput";
import {
  fetchAlerts,
  fetchMacroRegime,
  fetchMoonshots,
  fetchPortfolioSummary,
  fetchPositions,
  fetchResearchReports,
} from "@/lib/api";
import { formatCurrency, formatDate, formatPercent } from "@/lib/format";
import { stagger, rise } from "@/lib/motion";
import type {
  Alert,
  MacroRegime,
  Moonshot,
  PortfolioSummary,
  ResearchReport,
  SleevePosition,
} from "@/types";

type Range = "week" | "2weeks" | "custom";

interface DigestData {
  summary: PortfolioSummary;
  positions: SleevePosition[];
  alerts: Alert[];
  regime: MacroRegime;
  research: ResearchReport;
  moonshot: Moonshot;
}

interface DigestSectionSpec {
  id: string;
  title: string;
  html: string;
  markdown: string;
}

interface DigestResult {
  period: string;
  sections: DigestSectionSpec[];
  html: string;
  markdown: string;
}

const rangeOptions = [
  { value: "week" as Range, label: "This Week" },
  { value: "2weeks" as Range, label: "2 Weeks" },
  { value: "custom" as Range, label: "Custom" },
];

function getPeriodDates(range: Range, customStart: string, customEnd: string) {
  const end = new Date();
  const start = new Date();
  if (range === "week") {
    start.setDate(end.getDate() - 7);
  } else if (range === "2weeks") {
    start.setDate(end.getDate() - 14);
  } else {
    return {
      start: customStart ? new Date(customStart) : new Date(),
      end: customEnd ? new Date(customEnd) : new Date(),
    };
  }
  return { start, end };
}

function periodText(range: Range, customStart: string, customEnd: string) {
  if (range === "week") return "This Week";
  if (range === "2weeks") return "Past 2 Weeks";
  const { start, end } = getPeriodDates(range, customStart, customEnd);
  return `${formatDate(start.toISOString())} – ${formatDate(end.toISOString())}`;
}

function topMovers(positions: SleevePosition[]) {
  return positions
    .filter((p) => p.ticker !== "SGOV")
    .sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct))
    .slice(0, 4);
}

function severityVariant(severity: Alert["severity"]) {
  switch (severity) {
    case "critical":
      return "critical" as const;
    case "warning":
      return "warning" as const;
    case "info":
      return "info" as const;
    default:
      return "neutral" as const;
  }
}

function buildSections(data: DigestData): DigestSectionSpec[] {
  const movers = topMovers(data.positions);

  const performanceHtml = `
    <div class="grid grid-cols-2 gap-4 mb-4">
      <div class="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-sunken)/60 p-3">
        <p class="text-xs text-(--color-text-secondary)">Total Value</p>
        <p class="text-xl font-semibold tabular-nums text-(--color-text-primary)">${formatCurrency(data.summary.totalValue)}</p>
      </div>
      <div class="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-sunken)/60 p-3">
        <p class="text-xs text-(--color-text-secondary)">Day P&L</p>
        <p class="text-xl font-semibold tabular-nums ${data.summary.dayPnl >= 0 ? "text-(--color-accent-emerald)" : "text-(--color-accent-rose)"}">${data.summary.dayPnl >= 0 ? "+" : ""}${formatCurrency(data.summary.dayPnl)} (${formatPercent(data.summary.dayPnlPct)})</p>
      </div>
      <div class="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-sunken)/60 p-3">
        <p class="text-xs text-(--color-text-secondary)">Active Breaches</p>
        <p class="text-xl font-semibold tabular-nums ${data.summary.activeBreachCount > 0 ? "text-(--color-accent-rose)" : "text-(--color-accent-emerald)"}">${data.summary.activeBreachCount}</p>
      </div>
      <div class="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-sunken)/60 p-3">
        <p class="text-xs text-(--color-text-secondary)">Cash (SGOV)</p>
        <p class="text-xl font-semibold tabular-nums text-(--color-text-primary)">${formatCurrency(data.summary.cash)}</p>
      </div>
    </div>
    <div>
      <p class="text-sm font-medium text-(--color-text-secondary) mb-2">Top Movers</p>
      <div class="space-y-2">
        ${movers
          .map(
            (m) => `
          <div class="flex items-center justify-between rounded-lg border border-(--color-border-subtle) bg-(--color-surface-sunken)/40 px-3 py-2">
            <div>
              <span class="font-mono text-sm font-medium text-(--color-text-primary)">${m.ticker}</span>
              <span class="ml-2 text-xs text-(--color-text-secondary)">${m.name}</span>
            </div>
            <span class="text-sm font-medium tabular-nums ${m.changePct >= 0 ? "text-(--color-accent-emerald)" : "text-(--color-accent-rose)"}">${m.changePct >= 0 ? "+" : ""}${formatPercent(m.changePct)}</span>
          </div>
        `
          )
          .join("")}
      </div>
    </div>
  `;

  const performanceMarkdown = `**Total Value:** ${formatCurrency(data.summary.totalValue)}
**Day P&L:** ${data.summary.dayPnl >= 0 ? "+" : ""}${formatCurrency(data.summary.dayPnl)} (${formatPercent(data.summary.dayPnlPct)})
**Active Breaches:** ${data.summary.activeBreachCount}
**Cash (SGOV):** ${formatCurrency(data.summary.cash)}

**Top Movers:** ${movers.map((m) => `${m.ticker} ${formatPercent(m.changePct)}`).join(", ")}`;

  const breachesHtml =
    data.alerts.length > 0
      ? `<div class="space-y-3">
        ${data.alerts
          .map(
            (a) => `
          <div class="rounded-lg border ${a.severity === "critical" ? "border-(--color-accent-rose)/30 bg-(--color-accent-rose)/5" : a.severity === "warning" ? "border-(--color-accent-amber)/30 bg-(--color-accent-amber)/5" : "border-(--color-border-subtle) bg-(--color-surface-sunken)/40"} px-3 py-2">
            <div class="flex items-center justify-between">
              <span class="font-mono text-sm font-medium text-(--color-text-primary)">${a.ticker} · ${a.metric}</span>
              <span class="text-xs font-medium ${a.severity === "critical" ? "text-(--color-accent-rose)" : a.severity === "warning" ? "text-(--color-accent-amber)" : "text-(--color-accent-cyan)"}">${a.severity.toUpperCase()}</span>
            </div>
            <p class="mt-1 text-sm text-(--color-text-secondary)">${a.description}</p>
            <p class="mt-1 text-xs text-(--color-text-tertiary)">Current ${formatNumber(a.currentValue)} vs threshold ${formatNumber(a.thresholdValue)} · triggered ${formatDate(a.firstTriggeredAt)}</p>
          </div>
        `
          )
          .join("")}
      </div>`
      : `<p class="text-sm text-(--color-text-secondary)">No active breaches. Risk posture is clean.</p>`;

  const breachesMarkdown =
    data.alerts.length > 0
      ? data.alerts
          .map(
            (a) =>
              `- **${a.ticker}** — ${a.metric} (${a.severity.toUpperCase()}): ${a.description} Current ${formatNumber(a.currentValue)} vs threshold ${formatNumber(a.thresholdValue)}.`
          )
          .join("\n")
      : "No active breaches. Risk posture is clean.";

  const macroHtml = `
    <div class="flex flex-col sm:flex-row items-start gap-4">
      <div class="flex-1">
        <p class="text-lg font-semibold text-(--color-text-primary)">${data.regime.call}</p>
        <p class="mt-1 text-sm text-(--color-text-secondary)">${data.regime.rationale}</p>
        <p class="mt-2 text-xs text-(--color-text-tertiary)">Scanned ${formatDate(data.regime.scannedAt)} · ${data.regime.agent}</p>
      </div>
      <div class="shrink-0 w-32">
        <div class="h-2 w-full rounded-full bg-(--color-surface-elevated)">
          <div class="h-2 rounded-full bg-gradient-to-r from-(--color-accent-rose) via-(--color-accent-amber) to-(--color-accent-emerald)" style="width: ${data.regime.score}%"></div>
        </div>
        <p class="mt-1 text-center text-xs font-medium tabular-nums text-(--color-text-secondary)">Risk-On ${data.regime.score}%</p>
      </div>
    </div>
  `;

  const macroMarkdown = `**${data.regime.call}** (Risk-On score: ${data.regime.score}%)
${data.regime.rationale}
_Scanned ${formatDate(data.regime.scannedAt)} · ${data.regime.agent}_`;

  const researchHtml = `
    <div class="rounded-lg border border-(--color-border-subtle) bg-(--color-surface-sunken)/40 p-3">
      <p class="text-base font-medium text-(--color-text-primary)">${data.research.title}</p>
      <p class="mt-1 text-sm text-(--color-text-secondary)">${data.research.summary}</p>
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <span class="text-xs text-(--color-text-tertiary)">Verdict:</span>
        <span class="text-xs font-medium text-(--color-accent-violet)">${data.research.verdict}</span>
        <span class="text-xs text-(--color-text-tertiary)">· ${data.research.agent} · confidence ${data.research.confidence}%</span>
      </div>
    </div>
  `;

  const researchMarkdown = `**${data.research.title}**
${data.research.summary}
_Verdict: ${data.research.verdict} · ${data.research.agent} · confidence ${data.research.confidence}%_`;

  const moonshotHtml = `
    <div class="rounded-lg border border-(--color-border-subtle) bg-(--color-surface-sunken)/40 p-3">
      <div class="flex items-center justify-between">
        <div>
          <span class="font-mono text-lg font-semibold text-(--color-text-primary)">${data.moonshot.ticker}</span>
          <span class="ml-2 text-sm text-(--color-text-secondary)">${data.moonshot.name}</span>
        </div>
        <span class="rounded-full border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 px-2.5 py-1 text-xs font-medium text-(--color-text-secondary)">${data.moonshot.sector}</span>
      </div>
      <p class="mt-2 text-sm text-(--color-text-secondary)">${data.moonshot.thesis}</p>
      <p class="mt-2 text-sm text-(--color-text-primary)"><strong>Why now:</strong> ${data.moonshot.whyNow}</p>
      <div class="mt-3 flex items-center gap-3 text-xs">
        <span class="text-(--color-text-tertiary)">Conviction ${data.moonshot.conviction}%</span>
        <span class="text-(--color-text-tertiary)">Asymmetry: −${data.moonshot.asymmetry.downside}% / +${data.moonshot.asymmetry.upside}%</span>
      </div>
    </div>
  `;

  const moonshotMarkdown = `**${data.moonshot.ticker} — ${data.moonshot.name}** (${data.moonshot.sector})
${data.moonshot.thesis}
**Why now:** ${data.moonshot.whyNow}
Conviction: ${data.moonshot.conviction}% · Asymmetry: −${data.moonshot.asymmetry.downside}% / +${data.moonshot.asymmetry.upside}%`;

  return [
    { id: "performance", title: "Performance", html: performanceHtml, markdown: performanceMarkdown },
    { id: "breaches", title: "Breaches", html: breachesHtml, markdown: breachesMarkdown },
    { id: "macro", title: "Macro", html: macroHtml, markdown: macroMarkdown },
    { id: "research", title: "Top Research", html: researchHtml, markdown: researchMarkdown },
    { id: "moonshot", title: "Moonshot", html: moonshotHtml, markdown: moonshotMarkdown },
  ];
}

function compileDigest(
  data: DigestData,
  range: Range,
  customStart: string,
  customEnd: string
): DigestResult {
  const period = periodText(range, customStart, customEnd);
  const sections = buildSections(data);

  const sectionsHtml = sections
    .map(
      (s) => `
    <div style="margin-bottom: 28px;">
      <h2 style="font-size: 16px; font-weight: 600; color: var(--color-text-primary); margin: 0 0 12px 0;">${s.title}</h2>
      <div style="color: var(--color-text-secondary); line-height: 1.6;">${s.html}</div>
    </div>
  `
    )
    .join("");

  const html = `
<div style="max-width: 640px; margin: 0 auto; font-family: 'Geist Sans', ui-sans-serif, system-ui, sans-serif; color: var(--color-text-primary); background: var(--color-surface-elevated); border: 1px solid var(--color-border-subtle); border-radius: 16px; padding: 28px;">
  <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--color-border-subtle);">
    <div>
      <p style="font-size: 20px; font-weight: 700; margin: 0;">AlphaDesk Digest</p>
      <p style="font-size: 13px; color: var(--color-text-secondary); margin: 4px 0 0 0;">${period}</p>
    </div>
    <div style="width: 40px; height: 40px; border-radius: 10px; background: var(--color-accent-violet); display: flex; align-items: center; justify-content: center; color: var(--color-surface-base); font-weight: 700;">A</div>
  </div>
  ${sectionsHtml}
  <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--color-border-subtle); font-size: 12px; color: var(--color-text-tertiary); text-align: center;">
    Generated by AlphaDesk · Not investment advice
  </div>
</div>
`;

  const markdown = `# AlphaDesk Digest — ${period}\n\n${sections
    .map((s) => `## ${s.title}\n\n${s.markdown}`)
    .join("\n\n")}\n\n---\n\n_Generated by AlphaDesk · Not investment advice_`;

  return { period, sections, html, markdown };
}

export default function DigestView() {
  const [range, setRange] = useState<Range>("week");
  const [customStart, setCustomStart] = useState<string>("");
  const [customEnd, setCustomEnd] = useState<string>("");
  const [data, setData] = useState<DigestData | null>(null);
  const [digest, setDigest] = useState<DigestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedHtml, setCopiedHtml] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);

  useEffect(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - 7);
    setCustomStart(start.toISOString().split("T")[0]);
    setCustomEnd(end.toISOString().split("T")[0]);
  }, []);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [summary, positions, alerts, regime, reports, moonshots] = await Promise.all([
        fetchPortfolioSummary(),
        fetchPositions(),
        fetchAlerts(),
        fetchMacroRegime(),
        fetchResearchReports(),
        fetchMoonshots(),
      ]);
      const activeAlerts = alerts.filter((a) => a.state !== "resolved");
      const research = reports[0];
      const moonshot = moonshots.find((m) => m.sector !== "Technology") ?? moonshots[0];
      const nextData: DigestData = {
        summary,
        positions,
        alerts: activeAlerts,
        regime,
        research,
        moonshot,
      };
      setData(nextData);
      setDigest(compileDigest(nextData, range, customStart, customEnd));
    } catch {
      setError("We couldn’t assemble the digest right now. Try regenerating.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (data) {
      setDigest(compileDigest(data, range, customStart, customEnd));
    }
  }, [data, range, customStart, customEnd]);

  const handleRegenerate = () => {
    void load();
  };

  const copyToClipboard = async (text: string, type: "html" | "md") => {
    try {
      await navigator.clipboard.writeText(text);
      if (type === "html") {
        setCopiedHtml(true);
        setTimeout(() => setCopiedHtml(false), 2000);
      } else {
        setCopiedMd(true);
        setTimeout(() => setCopiedMd(false), 2000);
      }
    } catch {
      // ignore
    }
  };

  return (
    <div className="min-h-full">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="mx-auto max-w-7xl"
      >
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-(--color-accent-violet)">
              <Mail className="h-5 w-5" aria-hidden="true" />
              <span className="text-xs font-semibold uppercase tracking-wider">Email Digest</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">
                Digest
              </h1>
              <MockDataBadge label="Mixed mock inputs" />
            </div>
            <p className="mt-1 text-sm text-(--color-text-secondary)">
              Preview and copy your weekly AlphaDesk email digest.
            </p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <SegmentedControl
              options={rangeOptions}
              value={range}
              onChange={(value) => setRange(value as Range)}
              layoutId="digest-range"
            />
            <div className="flex items-center gap-2">
              <GlassButton
                variant="ghost"
                leftIcon={<RefreshCw className="h-4 w-4" />}
                onClick={handleRegenerate}
                disabled={loading}
              >
                Regenerate
              </GlassButton>
              <GlassButton
                variant="ghost"
                leftIcon={copiedHtml ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                onClick={() => digest && copyToClipboard(digest.html, "html")}
                disabled={!digest}
              >
                {copiedHtml ? "Copied" : "Copy HTML"}
              </GlassButton>
              <GlassButton
                variant="ghost"
                leftIcon={copiedMd ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                onClick={() => digest && copyToClipboard(digest.markdown, "md")}
                disabled={!digest}
              >
                {copiedMd ? "Copied" : "Copy Markdown"}
              </GlassButton>
            </div>
          </div>
        </div>

        {range === "custom" && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end"
          >
            <label className="flex-1">
              <span className="text-xs font-medium text-(--color-text-secondary)">Start date</span>
              <GlassInput
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                className="mt-1"
              />
            </label>
            <label className="flex-1">
              <span className="text-xs font-medium text-(--color-text-secondary)">End date</span>
              <GlassInput
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="mt-1"
              />
            </label>
          </motion.div>
        )}

        {error && (
          <div className="mt-8">
            <EmptyState
              title="Couldn’t load digest"
              description={error}
              icon={<RefreshCw className="h-6 w-6" />}
              action={{ label: "Try again", onClick: handleRegenerate }}
            />
          </div>
        )}

        {loading && !digest && (
          <GlassCard className="mx-auto mt-8 max-w-3xl p-6" glow="violet">
            <div className="mb-6 flex items-center justify-between">
              <Skeleton className="h-6 w-40" />
              <Skeleton className="h-10 w-10 rounded-lg" />
            </div>
            <div className="space-y-6">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="space-y-3">
                  <Skeleton className="h-5 w-32" />
                  <Skeleton className="h-24 w-full" />
                </div>
              ))}
            </div>
          </GlassCard>
        )}

        {digest && !error && (
          <GlassCard className="mx-auto mt-8 max-w-3xl p-6 sm:p-8" glow="violet">
            <div className="mb-6 flex items-start justify-between border-b border-(--color-border-subtle) pb-5">
              <div>
                <h2 className="text-xl font-semibold text-(--color-text-primary)">
                  AlphaDesk Digest
                </h2>
                <p className="mt-1 flex items-center gap-1.5 text-sm text-(--color-text-secondary)">
                  <Calendar className="h-3.5 w-3.5" aria-hidden="true" />
                  {digest.period}
                </p>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-(--color-accent-violet) text-sm font-bold text-(--color-surface-base)">
                A
              </div>
            </div>

            <motion.div
              initial="hidden"
              animate="visible"
              variants={stagger}
              className="space-y-8"
            >
              {digest.sections.map((section) => (
                <motion.section key={section.id} variants={rise} className="space-y-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-(--color-text-secondary)">
                    {section.title}
                  </h3>
                  {section.id === "performance" && data && (
                    <PerformancePreview positions={data.positions} summary={data.summary} />
                  )}
                  {section.id === "breaches" && data && (
                    <BreachesPreview alerts={data.alerts} />
                  )}
                  {section.id === "macro" && data && <MacroPreview regime={data.regime} />}
                  {section.id === "research" && data && <ResearchPreview report={data.research} />}
                  {section.id === "moonshot" && data && <MoonshotPreview moonshot={data.moonshot} />}
                </motion.section>
              ))}
            </motion.div>

            <div className="mt-8 border-t border-(--color-border-subtle) pt-4 text-center text-xs text-(--color-text-tertiary)">
              Generated by AlphaDesk · Not investment advice
            </div>
          </GlassCard>
        )}
      </motion.div>
    </div>
  );
}

function PerformancePreview({
  summary,
  positions,
}: {
  summary: PortfolioSummary;
  positions: SleevePosition[];
}) {
  const movers = topMovers(positions);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Total Value" value={formatCurrency(summary.totalValue)} />
        <Stat label="Day P&L">
          <DeltaChip value={summary.dayPnlPct} />
          <span className="ml-2 text-sm font-medium tabular-nums text-(--color-text-primary)">
            {summary.dayPnl >= 0 ? "+" : ""}
            {formatCurrency(summary.dayPnl)}
          </span>
        </Stat>
        <Stat
          label="Active Breaches"
          value={String(summary.activeBreachCount)}
          valueClass={
            summary.activeBreachCount > 0
              ? "text-(--color-accent-rose)"
              : "text-(--color-accent-emerald)"
          }
        />
        <Stat label="Cash (SGOV)" value={formatCurrency(summary.cash)} />
      </div>

      <div>
        <p className="mb-2 text-xs font-medium text-(--color-text-secondary)">Top Movers</p>
        <div className="space-y-2">
          {movers.map((m) => (
            <div
              key={m.ticker}
              className="flex items-center justify-between rounded-xl border border-(--color-border-subtle) bg-(--color-surface-sunken)/40 px-3 py-2 transition-colors hover:bg-(--color-surface-glass-hi)"
            >
              <div className="flex items-center gap-3">
                <span className="font-mono text-sm font-medium text-(--color-text-primary)">
                  {m.ticker}
                </span>
                <span className="hidden text-xs text-(--color-text-secondary) sm:inline">
                  {m.name}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <Sparkline
                  data={m.sparkline}
                  color={m.changePct >= 0 ? "emerald" : "rose"}
                  height={28}
                  className="w-20"
                />
                <DeltaChip value={m.changePct} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  valueClass,
  children,
}: {
  label: string;
  value?: string;
  valueClass?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-sunken)/60 p-3">
      <p className="text-xs text-(--color-text-secondary)">{label}</p>
      {value ? (
        <p className={`mt-1 text-lg font-semibold tabular-nums text-(--color-text-primary) ${valueClass ?? ""}`}>
          {value}
        </p>
      ) : (
        <div className={`mt-1 flex items-baseline gap-1 ${valueClass ?? ""}`}>{children}</div>
      )}
    </div>
  );
}

function BreachesPreview({ alerts }: { alerts: Alert[] }) {
  if (alerts.length === 0) {
    return (
      <p className="text-sm text-(--color-text-secondary)">
        No active breaches. Risk posture is clean.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {alerts.map((alert) => (
        <GlassCard
          key={alert.id}
          glow={alert.severity === "critical" ? "rose" : alert.severity === "warning" ? "amber" : false}
          className="p-3"
          hoverLift={false}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-(--color-text-primary)">
                  {alert.ticker}
                </span>
                <span className="text-xs text-(--color-text-secondary)">· {alert.metric}</span>
              </div>
              <p className="mt-1 text-sm text-(--color-text-secondary)">{alert.description}</p>
              <p className="mt-1 text-xs text-(--color-text-tertiary)">
                Current {formatNumber(alert.currentValue)} vs threshold{" "}
                {formatNumber(alert.thresholdValue)} · triggered{" "}
                {formatDate(alert.firstTriggeredAt)}
              </p>
            </div>
            <StatusBadge variant={severityVariant(alert.severity)} pulse={alert.severity === "critical"}>
              {alert.state === "new" ? "NEW" : alert.state === "acknowledged" ? "ACKED" : alert.state.toUpperCase()}
            </StatusBadge>
          </div>
        </GlassCard>
      ))}
    </div>
  );
}

function MacroPreview({ regime }: { regime: MacroRegime }) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
      <div className="flex-1 space-y-2">
        <p className="text-lg font-semibold text-(--color-text-primary)">{regime.call}</p>
        <p className="text-sm leading-relaxed text-(--color-text-secondary)">{regime.rationale}</p>
        <div className="flex items-center gap-2">
          <AgentTag name={regime.agent} confidence={regime.score} />
          <span className="text-xs text-(--color-text-tertiary)">
            Scanned {formatDate(regime.scannedAt)}
          </span>
        </div>
      </div>
      <div className="shrink-0">
        <Gauge value={regime.score} size={120} label="Risk-Off ↔ Risk-On" />
      </div>
    </div>
  );
}

function ResearchPreview({ report }: { report: ResearchReport }) {
  return (
    <GlassCard className="p-4" hoverLift={false}>
      <p className="text-base font-medium text-(--color-text-primary)">{report.title}</p>
      <p className="mt-1 text-sm text-(--color-text-secondary)">{report.summary}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {report.tickers.map((t) => (
          <span
            key={t}
            className="rounded-lg border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 px-2 py-0.5 font-mono text-xs text-(--color-text-secondary)"
          >
            {t}
          </span>
        ))}
        <span className="text-xs text-(--color-text-tertiary)">· {report.agent}</span>
        <AgentTag name="Verdict" confidence={report.confidence} />
        <span className="text-xs font-medium text-(--color-accent-violet)">{report.verdict}</span>
      </div>
    </GlassCard>
  );
}

function MoonshotPreview({ moonshot }: { moonshot: Moonshot }) {
  const ratio =
    moonshot.asymmetry.upside /
    (moonshot.asymmetry.upside + moonshot.asymmetry.downside);
  return (
    <GlassCard className="p-4" hoverLift={false}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-lg font-semibold text-(--color-text-primary)">
              {moonshot.ticker}
            </span>
            <span className="text-sm text-(--color-text-secondary)">{moonshot.name}</span>
          </div>
          <p className="mt-1 text-sm text-(--color-text-secondary)">{moonshot.thesis}</p>
        </div>
        <span className="shrink-0 rounded-full border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 px-2.5 py-1 text-xs font-medium text-(--color-text-secondary)">
          {moonshot.sector}
        </span>
      </div>

      <div className="mt-3 space-y-2">
        <p className="text-sm text-(--color-text-primary)">
          <span className="text-(--color-text-secondary)">Why now:</span> {moonshot.whyNow}
        </p>

        <div className="flex items-center gap-4">
          <div className="flex-1">
            <div className="mb-1 flex items-center justify-between text-xs text-(--color-text-secondary)">
              <span>Conviction</span>
              <span className="tabular-nums">{moonshot.conviction}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
              <div
                className="h-full rounded-full bg-(--color-accent-violet) transition-all duration-700"
                style={{ width: `${moonshot.conviction}%` }}
              />
            </div>
          </div>
          <div className="flex-1">
            <div className="mb-1 flex items-center justify-between text-xs text-(--color-text-secondary)">
              <span>Asymmetry</span>
              <span className="tabular-nums">
                −{moonshot.asymmetry.downside}% / +{moonshot.asymmetry.upside}%
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
              <div
                className="h-full rounded-full bg-gradient-to-r from-(--color-accent-rose) to-(--color-accent-emerald) transition-all duration-700"
                style={{ width: `${Math.min(ratio * 100, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </div>
    </GlassCard>
  );
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value);
}
