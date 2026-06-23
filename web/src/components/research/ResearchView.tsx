import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  BookOpen,
  Bot,
  Clock,
  FileText,
  Search,
  X,
} from "lucide-react";
import { fetchResearchReports, runResearchQuery } from "@/lib/api";
import type { ResearchReport } from "@/types";
import { stagger, rise, fade } from "@/lib/motion";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassInput } from "@/components/ui/GlassInput";
import { GlassButton } from "@/components/ui/GlassButton";
import { MockDataBadge } from "@/components/ui/MockDataBadge";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { AgentTag } from "@/components/ui/AgentTag";
import { StreamingText } from "@/components/ui/StreamingText";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { Drawer } from "@/components/ui/Drawer";
import { cn } from "@/lib/cn";

type Mode = "quick" | "deep";

const modeOptions: { value: Mode; label: string }[] = [
  { value: "quick", label: "Quick Scan" },
  { value: "deep", label: "Deep Dive" },
];

const sectionAgents: Record<
  string,
  { agent: string; confidence: number }
> = {
  Thesis: { agent: "Deep Research Analyst", confidence: 78 },
  "Bull case": { agent: "Bull Case Analyst", confidence: 70 },
  "Bear case": { agent: "Bear Case Analyst", confidence: 70 },
  Catalysts: { agent: "Event Screener", confidence: 62 },
  Risks: { agent: "Risk Analyst", confidence: 66 },
  Verdict: { agent: "Portfolio Strategist", confidence: 72 },
  Signal: { agent: "News Desk", confidence: 55 },
};

function getSectionMeta(heading: string) {
  return (
    sectionAgents[heading] ?? { agent: "Multi-Agent Research", confidence: 60 }
  );
}

function getInitials(name: string) {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function ScanlineHeader({ label }: { label: string }) {
  return (
    <div className="mb-5 flex items-center gap-3">
      <div className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-(--color-accent-cyan) opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-(--color-accent-cyan)" />
      </div>
      <span className="text-xs font-medium uppercase tracking-wider text-(--color-accent-cyan)">
        {label}
      </span>
      <div className="h-px flex-1 bg-gradient-to-r from-(--color-accent-cyan)/30 to-transparent" />
    </div>
  );
}

function StreamingReport({ report }: { report: ResearchReport }) {
  const [completedSections, setCompletedSections] = useState<Set<number>>(
    new Set()
  );

  return (
    <GlassCard glow="violet" className="p-5 sm:p-6">
      <ScanlineHeader label="Agents working" />

      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-(--color-text-primary)">
            {report.title}
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {report.tickers.map((ticker) => (
              <span
                key={ticker}
                className="rounded-md bg-(--color-surface-elevated) px-2 py-1 font-mono text-xs text-(--color-text-secondary)"
              >
                {ticker}
              </span>
            ))}
          </div>
        </div>
        <AgentTag name={report.agent} confidence={report.confidence} />
      </div>

      <motion.div
        variants={stagger}
        initial="hidden"
        animate="visible"
        className="space-y-4"
      >
        {report.sections.map((section, index) => {
          const meta = getSectionMeta(section.heading);
          const isVerdict = section.heading === "Verdict";
          const previousComplete =
            index === 0 || completedSections.has(index - 1);

          return (
            <motion.div
              key={`${section.heading}-${index}`}
              variants={rise}
              className={cn(
                "rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/40 p-4",
                isVerdict && "border-(--color-accent-violet)/30 bg-(--color-accent-violet)/5"
              )}
            >
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-secondary)">
                  {section.heading}
                </h4>
                <AgentTag
                  name={meta.agent}
                  confidence={meta.confidence}
                  className="scale-90"
                />
              </div>
              {previousComplete ? (
                <StreamingText
                  text={section.content}
                  speed={24}
                  showScanline={false}
                  onComplete={() => {
                    setCompletedSections((prev) => new Set([...prev, index]));
                  }}
                />
              ) : (
                <span className="inline-flex items-center gap-2 text-sm text-(--color-text-tertiary)">
                  <span className="h-1.5 w-1.5 rounded-full bg-(--color-text-tertiary)" />
                  Awaiting prior section…
                </span>
              )}
            </motion.div>
          );
        })}
      </motion.div>

      <div className="mt-5 flex items-center justify-between border-t border-(--color-border-subtle) pt-4">
        <span className="text-xs text-(--color-text-secondary)">
          {report.freshness}
        </span>
        {completedSections.size === report.sections.length && (
          <span className="text-xs font-medium text-(--color-accent-emerald)">
            Report complete
          </span>
        )}
      </div>
    </GlassCard>
  );
}

function ReportCard({
  report,
  onClick,
}: {
  report: ResearchReport;
  onClick: () => void;
}) {
  const [summarizing, setSummarizing] = useState(false);

  return (
    <GlassCard className="p-4" hoverLift>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-(--color-text-primary)">
            {report.title}
          </h3>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {report.tickers.map((ticker) => (
              <span
                key={ticker}
                className="rounded-md bg-(--color-surface-elevated) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-secondary)"
              >
                {ticker}
              </span>
            ))}
          </div>
        </div>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 font-mono text-[10px] text-(--color-text-secondary)">
          {getInitials(report.agent)}
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-(--color-text-tertiary)">
        <div className="flex items-center gap-1.5">
          <Clock className="h-3 w-3" />
          <span>{report.freshness}</span>
        </div>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[10px] font-medium",
            report.tier === "deep"
              ? "bg-(--color-accent-violet)/10 text-(--color-accent-violet)"
              : "bg-(--color-accent-cyan)/10 text-(--color-accent-cyan)"
          )}
        >
          {report.tier}
        </span>
      </div>

      {summarizing && (
        <div className="mt-3 border-t border-(--color-border-subtle) pt-3">
          <StreamingText
            text={report.summary}
            speed={28}
            className="text-xs leading-relaxed text-(--color-text-secondary)"
          />
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <GlassButton
          variant="ghost"
          sparkle
          className="h-7 px-2.5 text-xs"
          onClick={(e) => {
            e.stopPropagation();
            setSummarizing(true);
          }}
          disabled={summarizing}
        >
          Summarize
        </GlassButton>
        <GlassButton
          variant="ghost"
          className="h-7 px-2.5 text-xs"
          onClick={onClick}
        >
          Read
        </GlassButton>
      </div>
    </GlassCard>
  );
}

function ReportReader({ report }: { report: ResearchReport }) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-(--color-text-primary)">
          {report.title}
        </h2>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <AgentTag name={report.agent} confidence={report.confidence} />
          <span className="text-xs text-(--color-text-tertiary)">
            {report.freshness}
          </span>
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-medium",
              report.tier === "deep"
                ? "bg-(--color-accent-violet)/10 text-(--color-accent-violet)"
                : "bg-(--color-accent-cyan)/10 text-(--color-accent-cyan)"
            )}
          >
            {report.tier}
          </span>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {report.tickers.map((ticker) => (
            <span
              key={ticker}
              className="rounded-md bg-(--color-surface-elevated) px-2 py-1 font-mono text-xs text-(--color-text-secondary)"
            >
              {ticker}
            </span>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-(--color-accent-violet)/20 bg-(--color-accent-violet)/5 p-4">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-(--color-accent-violet)">
          Verdict
        </h3>
        <p className="text-sm font-medium text-(--color-text-primary)">
          {report.verdict}
        </p>
      </div>

      <div className="space-y-4">
        {report.sections.map((section, index) => {
          const meta = getSectionMeta(section.heading);
          return (
            <div
              key={`${section.heading}-${index}`}
              className="rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/40 p-4"
            >
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-secondary)">
                  {section.heading}
                </h4>
                <AgentTag
                  name={meta.agent}
                  confidence={meta.confidence}
                  className="scale-90"
                />
              </div>
              <p className="text-sm leading-relaxed text-(--color-text-primary)">
                {section.content}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function ResearchView() {
  const [mode, setMode] = useState<Mode>("quick");
  const [query, setQuery] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [liveReport, setLiveReport] = useState<ResearchReport | null>(null);
  const [reports, setReports] = useState<ResearchReport[]>([]);
  const [loadingReports, setLoadingReports] = useState(true);
  const [selectedReport, setSelectedReport] = useState<ResearchReport | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchResearchReports()
      .then((data) => {
        if (!cancelled) setReports(data);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load research reports.");
      })
      .finally(() => {
        if (!cancelled) setLoadingReports(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRun = async () => {
    const trimmed = query.trim();
    if (!trimmed) return;

    setIsRunning(true);
    setLiveReport(null);
    setError(null);

    try {
      const report = await runResearchQuery(trimmed);
      // Force the selected tier to match the mode.
      setLiveReport({ ...report, tier: mode });
      setReports((prev) => [report, ...prev]);
    } catch {
      setError("Research run failed. Please try again.");
    } finally {
      setIsRunning(false);
    }
  };

  const filteredReports = useMemo(
    () => reports.filter((r) => !liveReport || r.id !== liveReport.id),
    [reports, liveReport]
  );

  return (
    <div className="min-h-full">
      <motion.div
        variants={stagger}
        initial="hidden"
        animate="visible"
        className="mx-auto max-w-7xl space-y-6"
      >
        <motion.div
          variants={rise}
          className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold text-(--color-text-primary)">
                Research
              </h1>
              <MockDataBadge />
            </div>
            <p className="text-sm text-(--color-text-secondary)">
              Cross-agent scans and deep-dive reports.
            </p>
          </div>
          <SegmentedControl
            options={modeOptions}
            value={mode}
            onChange={(value) => setMode(value as Mode)}
            layoutId="research-mode"
          />
        </motion.div>

        <motion.div variants={rise}>
          <GlassCard className="p-1">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-(--color-text-tertiary)" />
                <GlassInput
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleRun();
                  }}
                  placeholder="Research a ticker or theme…"
                  className="border-0 pl-10 shadow-none focus:ring-0"
                  disabled={isRunning}
                  aria-label="Research query"
                />
              </div>
              <GlassButton
                sparkle
                onClick={handleRun}
                disabled={isRunning || !query.trim()}
                className="shrink-0"
              >
                {isRunning ? "Running…" : "Run"}
              </GlassButton>
              <MockDataBadge label="Mock run" className="self-start sm:self-center" />
            </div>
          </GlassCard>
        </motion.div>

        <AnimatePresence mode="wait">
          {isRunning && !liveReport && (
            <motion.div
              key="running"
              variants={fade}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              <GlassCard glow="violet" className="p-5 sm:p-6">
                <ScanlineHeader label="Agents working" />
                <div className="space-y-4">
                  <Skeleton className="h-6 w-3/4" />
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-20 w-5/6" />
                </div>
              </GlassCard>
            </motion.div>
          )}

          {liveReport && (
            <motion.div
              key={liveReport.id}
              variants={fade}
              initial="hidden"
              animate="visible"
              exit="exit"
            >
              <StreamingReport report={liveReport} />
            </motion.div>
          )}
        </AnimatePresence>

        {error && (
          <GlassCard glow="rose" className="p-4">
            <div className="flex items-center gap-2 text-sm text-(--color-accent-rose)">
              <X className="h-4 w-4" />
              {error}
            </div>
          </GlassCard>
        )}

        <motion.div variants={rise}>
          <div className="mb-3 flex items-center gap-2">
            <FileText className="h-4 w-4 text-(--color-text-secondary)" />
            <h2 className="text-sm font-semibold text-(--color-text-primary)">
              Past Reports
            </h2>
          </div>

          {loadingReports ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-40 w-full" />
              ))}
            </div>
          ) : filteredReports.length === 0 ? (
            <EmptyState
              title="No reports yet"
              description="Run your first research query to generate a quick scan or deep dive."
              icon={<BookOpen className="h-6 w-6" />}
              action={{
                label: "Try a query",
                onClick: () => {
                  setQuery("AI compute supply chain");
                },
              }}
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <AnimatePresence>
                {filteredReports.map((report) => (
                  <motion.div
                    key={report.id}
                    layout
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.96 }}
                    transition={{ duration: 0.3 }}
                  >
                    <ReportCard
                      report={report}
                      onClick={() => setSelectedReport(report)}
                    />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </motion.div>
      </motion.div>

      <Drawer
        open={selectedReport !== null}
        onClose={() => setSelectedReport(null)}
        title={
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-(--color-accent-violet)" />
            <span>Research Reader</span>
          </div>
        }
      >
        {selectedReport && <ReportReader report={selectedReport} />}
      </Drawer>
    </div>
  );
}
