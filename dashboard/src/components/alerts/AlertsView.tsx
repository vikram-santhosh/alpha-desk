import { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Bell, BellOff, ShieldCheck } from "lucide-react";
import { fetchAlerts } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { MockDataBadge } from "@/components/ui/MockDataBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDateTime, formatPercent } from "@/lib/format";
import { stagger, rise } from "@/lib/motion";
import { cn } from "@/lib/cn";
import type { Alert, AlertState } from "@/types";
import { AlertCard } from "./AlertCard";
import { AlertTimeline } from "./AlertTimeline";
import { ThresholdRulesCard } from "./ThresholdRulesCard";

function HeaderStat({ label, value, accent = "violet" }: { label: string; value: React.ReactNode; accent?: "rose" | "amber" | "emerald" | "violet" }) {
  const accentText = {
    rose: "text-(--color-accent-rose)",
    amber: "text-(--color-accent-amber)",
    emerald: "text-(--color-accent-emerald)",
    violet: "text-(--color-accent-violet)",
  }[accent];

  return (
    <div className="flex flex-col">
      <span className="text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)">{label}</span>
      <span className={cn("text-lg font-semibold tabular-nums", accentText)}>{value}</span>
    </div>
  );
}

const historyStateLabel: Record<AlertState, string> = {
  new: "NEW",
  acknowledged: "ACKED",
  muted: "MUTED",
  resolved: "RESOLVED",
};

const historyStateVariant: Record<AlertState, import("@/components/ui/StatusBadge").StatusVariant> = {
  new: "critical",
  acknowledged: "warning",
  muted: "neutral",
  resolved: "success",
};

export default function AlertsView() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchAlerts()
      .then((data) => {
        if (!cancelled) setAlerts(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleAcknowledge = (id: string) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, state: "acknowledged" as AlertState } : a))
    );
  };

  const handleMute = (id: string) => {
    setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, state: "muted" as AlertState } : a)));
  };

  const activeAlerts = useMemo(
    () => alerts.filter((a) => a.state === "new" || a.state === "acknowledged"),
    [alerts]
  );

  const historyAlerts = useMemo(
    () => alerts.filter((a) => a.state === "muted" || a.state === "resolved"),
    [alerts]
  );

  const criticalCount = activeAlerts.filter((a) => a.severity === "critical").length;
  const warningCount = activeAlerts.filter((a) => a.severity === "warning").length;

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-4 w-72" />
        </div>
        <div className="mb-6 grid gap-4 md:grid-cols-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-72" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-7xl py-12">
        <EmptyState
          title="Couldn’t load alerts"
          description={error.message || "Something went wrong fetching breach data."}
          icon={<Bell className="h-6 w-6" />}
          action={{ label: "Try again", onClick: () => window.location.reload() }}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <motion.div
        initial={reduceMotion ? "visible" : "hidden"}
        animate="visible"
        variants={stagger}
        className="space-y-6"
      >
        <motion.div variants={rise} className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">
                Alerts
              </h1>
              <MockDataBadge />
            </div>
            <p className="text-sm text-(--color-text-secondary)">
              Active breaches, state history, and threshold configuration.
            </p>
          </div>
          <GlassCard className="flex items-center gap-6 px-5 py-3">
            <HeaderStat label="Active" value={activeAlerts.length} accent={criticalCount > 0 ? "rose" : "emerald"} />
            <div className="h-8 w-px bg-(--color-border-subtle)" aria-hidden="true" />
            <HeaderStat label="Critical" value={criticalCount} accent="rose" />
            <div className="h-8 w-px bg-(--color-border-subtle)" aria-hidden="true" />
            <HeaderStat label="Warning" value={warningCount} accent="amber" />
          </GlassCard>
        </motion.div>

        <motion.section variants={rise}>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-(--color-text-primary)">Active Breaches</h2>
            {activeAlerts.length > 0 && (
              <StatusBadge variant={criticalCount > 0 ? "critical" : "warning"} pulse={criticalCount > 0}>
                {activeAlerts.length} open
              </StatusBadge>
            )}
          </div>

          {activeAlerts.length === 0 ? (
            <EmptyState
              title="All clear"
              description="No active breaches. The portfolio is within configured thresholds."
              icon={<ShieldCheck className="h-6 w-6" />}
            />
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {activeAlerts.map((alert) => (
                <AlertCard
                  key={alert.id}
                  alert={alert}
                  onAcknowledge={handleAcknowledge}
                  onMute={handleMute}
                />
              ))}
            </div>
          )}
        </motion.section>

        {historyAlerts.length > 0 && (
          <motion.section variants={rise}>
            <h2 className="mb-3 text-base font-semibold text-(--color-text-primary)">History</h2>
            <GlassCard className="divide-y divide-(--color-border-subtle)">
              {historyAlerts.map((alert) => (
                <div
                  key={alert.id}
                  className="flex flex-col gap-2 px-5 py-4 transition-colors hover:bg-(--color-surface-glass-hi)/30 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex items-center gap-3">
                    <BellOff className="h-4 w-4 text-(--color-text-tertiary)" aria-hidden="true" />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-semibold text-(--color-text-primary)">
                          {alert.ticker}
                        </span>
                        <StatusBadge variant={historyStateVariant[alert.state]}>
                          {historyStateLabel[alert.state]}
                        </StatusBadge>
                      </div>
                      <p className="text-xs text-(--color-text-secondary)">{alert.description}</p>
                    </div>
                  </div>
                  <div className="flex flex-col items-start gap-1 sm:items-end">
                    <AlertTimeline state={alert.state} />
                    <span className="text-xs tabular-nums text-(--color-text-tertiary)">
                      {alert.resolvedAt
                        ? `Resolved ${formatDateTime(alert.resolvedAt)}`
                        : `Triggered ${formatDateTime(alert.firstTriggeredAt)}`}
                    </span>
                    <span className="text-xs tabular-nums text-(--color-text-tertiary)">
                      {formatPercent(alert.currentValue)} vs {formatPercent(alert.thresholdValue)}
                    </span>
                  </div>
                </div>
              ))}
            </GlassCard>
          </motion.section>
        )}

        <motion.section variants={rise}>
          <ThresholdRulesCard />
        </motion.section>
      </motion.div>
    </div>
  );
}
