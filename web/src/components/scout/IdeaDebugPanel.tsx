import { motion } from "motion/react";
import type { DimensionScore, IdeaDebug } from "@/types";

function factorColor(factor: string): string {
  const f = factor.trimStart();
  if (f.startsWith("+")) return "text-(--color-accent-emerald)";
  if (f.startsWith("-")) return "text-(--color-accent-rose)";
  return "text-(--color-text-tertiary)";
}

function DimensionBar({ dim, maxContribution }: { dim: DimensionScore; maxContribution: number }) {
  const widthPct = Math.max(0, Math.min(100, dim.score));
  const label = dim.name.replace(/_/g, " ");
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-28 shrink-0 capitalize text-(--color-text-secondary)">{label}</span>
      <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-(--color-surface-glass)">
        <motion.div
          className="h-full rounded-full bg-(--color-accent-cyan)/70"
          initial={{ width: 0 }}
          animate={{ width: `${widthPct}%` }}
          transition={{ duration: 0.4 }}
        />
      </div>
      <span className="w-8 shrink-0 text-right tabular-nums text-(--color-text-tertiary)">{Math.round(dim.score)}</span>
      <span className="w-10 shrink-0 text-right tabular-nums text-(--color-text-tertiary)" title="weight">
        ×{dim.weight.toFixed(2)}
      </span>
      <span
        className={`w-10 shrink-0 text-right tabular-nums font-medium ${
          dim.contribution >= maxContribution * 0.9 ? "text-(--color-text-primary)" : "text-(--color-text-secondary)"
        }`}
        title="contribution to composite"
      >
        {dim.contribution.toFixed(1)}
      </span>
    </div>
  );
}

export function IdeaDebugPanel({ debug }: { debug: IdeaDebug }) {
  const dims = [...debug.dimensions].sort((a, b) => b.contribution - a.contribution);
  const maxContribution = dims.reduce((m, d) => Math.max(m, d.contribution), 0) || 1;

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.25 }}
      className="mt-3 overflow-hidden rounded-xl border border-(--color-border-subtle) bg-(--color-surface-base)/40 p-3"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-(--color-text-secondary)">
          Why this ranked here
        </span>
        <div className="flex items-center gap-2">
          {debug.synthesis_source && (
            <span
              className="rounded-full bg-(--color-surface-glass) px-2 py-0.5 text-[10px] text-(--color-text-tertiary)"
              title="How the ranking was produced"
            >
              {debug.synthesis_source}
            </span>
          )}
          <span className="text-xs tabular-nums text-(--color-text-primary)">composite {debug.composite.toFixed(1)}</span>
        </div>
      </div>

      {/* Dimension contributions */}
      {dims.length > 0 && (
        <div className="space-y-1.5">
          {dims.map((d) => (
            <DimensionBar key={d.name} dim={d} maxContribution={maxContribution} />
          ))}
        </div>
      )}

      {/* Business-quality factors (the human-readable "why") */}
      {debug.factors.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-[11px] uppercase tracking-wide text-(--color-text-tertiary)">Business quality</div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {debug.factors.map((f, i) => (
              <span key={i} className={`text-xs tabular-nums ${factorColor(f)}`}>
                {f}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Valuation / forward-upside factors */}
      {debug.valuation_factors && debug.valuation_factors.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-[11px] uppercase tracking-wide text-(--color-text-tertiary)">Valuation &amp; upside</div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {debug.valuation_factors.map((f, i) => (
              <span key={i} className={`text-xs tabular-nums ${factorColor(f)}`}>
                {f}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Provenance */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-(--color-text-tertiary)">
        <span>source: {debug.source}</span>
        <span title={debug.corroborating_sources.join(", ")}>
          corroboration: {debug.corroboration_count}
          {debug.corroborating_sources.length > 0 && ` (${debug.corroborating_sources.join(", ")})`}
        </span>
      </div>
    </motion.div>
  );
}
