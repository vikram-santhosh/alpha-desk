import { cn } from "@/lib/cn";
import type { AlertState } from "@/types";

const stateLabels: Record<AlertState, string> = {
  new: "NEW",
  acknowledged: "ACK",
  muted: "MUTED",
  resolved: "RESOLVED",
};

const stateDotStyles: Record<AlertState, string> = {
  new: "bg-(--color-accent-rose)",
  acknowledged: "bg-(--color-accent-amber)",
  muted: "bg-(--color-text-tertiary)",
  resolved: "bg-(--color-accent-emerald)",
};

interface AlertTimelineProps {
  state: AlertState;
  className?: string;
}

export function AlertTimeline({ state, className }: AlertTimelineProps) {
  const path: AlertState[] =
    state === "resolved"
      ? ["new", "acknowledged", "resolved"]
      : state === "muted"
        ? ["new", "muted"]
        : state === "acknowledged"
          ? ["new", "acknowledged"]
          : ["new"];

  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      {path.map((s, idx) => (
        <div key={s} className="flex items-center gap-1.5">
          <span
            className={cn(
              "h-2 w-2 rounded-full ring-2 ring-(--color-surface-elevated)",
              stateDotStyles[s]
            )}
            aria-hidden="true"
          />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-secondary)">
            {stateLabels[s]}
          </span>
          {idx < path.length - 1 && (
            <div className="mx-1 h-px w-5 bg-(--color-border-subtle)" aria-hidden="true" />
          )}
        </div>
      ))}
    </div>
  );
}
