import { GlassCard } from "@/components/ui/GlassCard";
import { positions } from "@/data/portfolio";
import { formatPercent } from "@/lib/format";
import { cn } from "@/lib/cn";

export function ThresholdRulesCard() {
  return (
    <GlassCard className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-(--color-text-primary)">Threshold Rules</h3>
          <p className="text-sm text-(--color-text-secondary)">
            Read-only per-position guardrails used by the breach monitor.
          </p>
        </div>
        <span className="rounded-lg border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 px-2.5 py-1 text-xs font-medium text-(--color-text-secondary)">
          Read-only
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {positions.map((position) => {
          const target = position.weight * 100;
          const isCash = position.ticker === "SGOV";
          const maxPosition = isCash ? Math.max(target, 10) : target + 2;

          return (
            <div
              key={position.ticker}
              className={cn(
                "rounded-xl border border-(--color-border-subtle) bg-(--color-surface-sunken)/60 p-3",
                "transition-colors hover:bg-(--color-surface-elevated)/60"
              )}
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="font-mono text-sm font-semibold text-(--color-text-primary)">
                  {position.ticker}
                </span>
                <span className="text-xs text-(--color-text-tertiary)">{position.theme}</span>
              </div>
              <div className="space-y-1.5 text-xs text-(--color-text-secondary)">
                <div className="flex items-center justify-between">
                  <span>Target weight</span>
                  <span className="tabular-nums font-medium text-(--color-text-primary)">
                    {formatPercent(target)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span>{isCash ? "Minimum allocation" : "Max position"}</span>
                  <span className="tabular-nums font-medium text-(--color-text-primary)">
                    {formatPercent(maxPosition)}
                  </span>
                </div>
                {!isCash && (
                  <div className="flex items-center justify-between">
                    <span>Thesis drawdown limit</span>
                    <span className="tabular-nums font-medium text-(--color-accent-rose)">
                      -15.0%
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}
