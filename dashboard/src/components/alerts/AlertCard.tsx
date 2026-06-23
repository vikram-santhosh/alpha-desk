import { useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import {
  AlertTriangle,
  Bell,
  Check,
  Info,
  ShieldCheck,
  Sparkles,
  VolumeX,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { GlassButton } from "@/components/ui/GlassButton";
import { StreamingText } from "@/components/ui/StreamingText";
import { AgentTag } from "@/components/ui/AgentTag";
import { askAlphaDesk } from "@/lib/api";
import { formatDateTime, formatPercent } from "@/lib/format";
import { cn } from "@/lib/cn";
import type { Alert, AlertSeverity, AlertState } from "@/types";
import { AlertTimeline } from "./AlertTimeline";

interface AlertCardProps {
  alert: Alert;
  onAcknowledge: (id: string) => void;
  onMute: (id: string) => void;
  className?: string;
}

const severityMeta: Record<
  AlertSeverity,
  { glow: "rose" | "amber" | "cyan"; bar: string; icon: typeof AlertTriangle }
> = {
  critical: { glow: "rose", bar: "bg-(--color-accent-rose)", icon: AlertTriangle },
  warning: { glow: "amber", bar: "bg-(--color-accent-amber)", icon: Bell },
  info: { glow: "cyan", bar: "bg-(--color-accent-cyan)", icon: Info },
};

const stateBadgeVariant: Record<AlertState, import("@/components/ui/StatusBadge").StatusVariant> = {
  new: "critical",
  acknowledged: "warning",
  muted: "neutral",
  resolved: "success",
};

const stateLabel: Record<AlertState, string> = {
  new: "NEW",
  acknowledged: "ACKED",
  muted: "MUTED",
  resolved: "RESOLVED",
};

function thresholdRatio(current: number, threshold: number): number {
  if (threshold === 0) return 0;
  return Math.min(Math.abs(current / threshold), 1.25);
}

export function AlertCard({ alert, onAcknowledge, onMute, className }: AlertCardProps) {
  const meta = severityMeta[alert.severity];
  const SeverityIcon = meta.icon;
  const ratio = thresholdRatio(alert.currentValue, alert.thresholdValue);
  const isUnderThreshold = Math.abs(alert.currentValue) < Math.abs(alert.thresholdValue);
  const reduceMotion = useReducedMotion();

  const [explaining, setExplaining] = useState(false);
  const [explanation, setExplanation] = useState<{
    text: string;
    agent: string;
    confidence: number;
  } | null>(null);

  const handleExplain = async () => {
    setExplaining(true);
    setExplanation(null);
    try {
      const result = await askAlphaDesk(
        `Explain the ${alert.severity} breach for ${alert.ticker} (${alert.metric}): ${alert.description}`
      );
      setExplanation({
        text: result.answer,
        agent: result.agent,
        confidence: result.confidence,
      });
    } finally {
      setExplaining(false);
    }
  };

  return (
    <motion.div
      layout={!reduceMotion}
      layoutId={alert.id}
      initial={reduceMotion ? { opacity: 1 } : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.35, ease: [0.25, 0.46, 0.45, 0.94] }}
      className={className}
    >
      <GlassCard
        glow={meta.glow}
        hoverLift
        className={cn(
          "flex flex-col gap-4 p-5",
          alert.severity === "critical" && "animate-[pulse-glow_2.5s_ease-in-out_infinite]"
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border",
                alert.severity === "critical" &&
                  "border-(--color-accent-rose)/30 bg-(--color-accent-rose)/10 text-(--color-accent-rose)",
                alert.severity === "warning" &&
                  "border-(--color-accent-amber)/30 bg-(--color-accent-amber)/10 text-(--color-accent-amber)",
                alert.severity === "info" &&
                  "border-(--color-accent-cyan)/30 bg-(--color-accent-cyan)/10 text-(--color-accent-cyan)"
              )}
            >
              <SeverityIcon className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-lg font-semibold text-(--color-text-primary)">
                  {alert.ticker}
                </span>
                <StatusBadge
                  variant={stateBadgeVariant[alert.state]}
                  pulse={alert.state === "new"}
                >
                  {stateLabel[alert.state]}
                </StatusBadge>
              </div>
              <p className="text-sm text-(--color-text-secondary)">{alert.metric}</p>
            </div>
          </div>
          <span className="text-xs tabular-nums text-(--color-text-tertiary)">
            {formatDateTime(alert.firstTriggeredAt)}
          </span>
        </div>

        <p className="text-sm leading-relaxed text-(--color-text-primary)">{alert.description}</p>

        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-(--color-text-secondary)">
            <span>
              Current{" "}
              <strong className="tabular-nums text-(--color-text-primary)">
                {formatPercent(alert.currentValue)}
              </strong>
            </span>
            <span>
              Threshold{" "}
              <strong className="tabular-nums text-(--color-text-primary)">
                {formatPercent(alert.thresholdValue)}
              </strong>
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
            <motion.div
              className={cn("h-full rounded-full", meta.bar)}
              initial={{ width: 0 }}
              animate={{ width: `${ratio * 100}%` }}
              transition={{ duration: reduceMotion ? 0 : 0.7, ease: [0.25, 0.46, 0.45, 0.94] }}
            />
          </div>
          <p className="text-xs text-(--color-text-tertiary)">
            {isUnderThreshold
              ? `${formatPercent(Math.abs(alert.thresholdValue - alert.currentValue))} away from threshold`
              : `${formatPercent(Math.abs(alert.currentValue - alert.thresholdValue))} over threshold`}
          </p>
        </div>

        <AlertTimeline state={alert.state} />

        <div className="flex flex-wrap items-center gap-2 pt-1">
          {alert.state !== "acknowledged" && alert.state !== "resolved" && (
            <GlassButton
              variant="ghost"
              leftIcon={<Check className="h-4 w-4" />}
              onClick={() => onAcknowledge(alert.id)}
              className="text-xs"
            >
              Acknowledge
            </GlassButton>
          )}
          {alert.state !== "muted" && alert.state !== "resolved" && (
            <GlassButton
              variant="ghost"
              leftIcon={<VolumeX className="h-4 w-4" />}
              onClick={() => onMute(alert.id)}
              className="text-xs"
            >
              Mute
            </GlassButton>
          )}
          {alert.state === "resolved" && (
            <StatusBadge variant="success" icon={<ShieldCheck className="h-3.5 w-3.5" />}>
              Resolved
            </StatusBadge>
          )}
          <GlassButton
            variant="ghost"
            sparkle
            disabled={explaining}
            onClick={handleExplain}
            className="ml-auto text-xs text-(--color-accent-violet) hover:text-(--color-accent-violet)"
          >
            {explaining ? "Analyzing…" : "Explain this breach"}
          </GlassButton>
        </div>

        <AnimatePresence>
          {explanation && (
            <motion.div
              initial={reduceMotion ? { opacity: 1 } : { opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={reduceMotion ? { opacity: 0 } : { opacity: 0, height: 0 }}
              transition={{ duration: reduceMotion ? 0 : 0.25 }}
              className="overflow-hidden"
            >
              <GlassCard
                glow="violet"
                className="mt-1 border-(--color-accent-violet)/20 bg-(--color-accent-violet)/5 p-4"
              >
                <div className="mb-3 flex items-center justify-between gap-3">
                  <AgentTag name={explanation.agent} confidence={explanation.confidence} />
                  <GlassButton
                    variant="icon"
                    onClick={() => setExplanation(null)}
                    aria-label="Dismiss explanation"
                  >
                    <Sparkles className="h-4 w-4" />
                  </GlassButton>
                </div>
                <StreamingText
                  text={explanation.text}
                  speed={22}
                  showScanline
                  className="text-sm leading-relaxed text-(--color-text-primary)"
                />
              </GlassCard>
            </motion.div>
          )}
        </AnimatePresence>
      </GlassCard>
    </motion.div>
  );
}
