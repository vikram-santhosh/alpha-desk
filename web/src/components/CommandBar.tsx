import { useEffect, useMemo, useState } from "react";

import type { CouncilRunRequest, ModelOption } from "../api/types";

type CommandBarProps = {
  roster: ModelOption[];
  status: string;
  onRun: (request: CouncilRunRequest) => void;
  onScout?: () => void;
  scoutStatus?: "idle" | "loading" | "complete" | "error";
};

function normalizeTicker(value: string) {
  return value.trim().toUpperCase();
}

export function CommandBar({ roster, status, onRun, onScout, scoutStatus = "idle" }: CommandBarProps) {
  const [ticker, setTicker] = useState("");
  const [enabledById, setEnabledById] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(roster.map((model) => [model.model_id, model.enabled]))
  );

  useEffect(() => {
    setEnabledById(Object.fromEntries(roster.map((model) => [model.model_id, model.enabled])));
  }, [roster]);

  const enabledModels = useMemo(
    () => roster.filter((model) => enabledById[model.model_id]).map((model) => model.model_id),
    [enabledById, roster]
  );
  const cleanedTicker = normalizeTicker(ticker);
  const canRun = cleanedTicker.length > 0 && enabledModels.length > 0;

  function submit() {
    if (!canRun) return;
    onRun({ ticker: cleanedTicker, models: enabledModels });
  }

  function toggleModel(modelId: string) {
    setEnabledById((current) => ({ ...current, [modelId]: !current[modelId] }));
  }

  return (
    <section className="glass flex flex-col gap-5 p-5" aria-label="Council command bar">
      <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p className="data-text text-xs uppercase text-[var(--muted)]">Model council</p>
          <h2 className="font-display text-3xl font-bold tracking-normal md:text-4xl">Run a ticker debate</h2>
        </div>

        <div className="flex w-full flex-col gap-3 xl:max-w-2xl">
          <label className="data-text text-xs uppercase text-[var(--muted)]" htmlFor="ticker-input">
            Ticker or idea
          </label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              id="ticker-input"
              className="data-text focus-ring min-h-12 flex-1 rounded-2xl border border-white/10 bg-white/[.045] px-4 text-sm text-[var(--text)] placeholder:text-[var(--muted)]"
              placeholder="NVDA"
              value={ticker}
              onChange={(event) => setTicker(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") submit();
              }}
            />
            <button
              type="button"
              className="focus-ring min-h-12 rounded-2xl border border-[var(--gold)]/70 bg-[var(--gold)]/10 px-5 font-display text-sm font-semibold text-[var(--text)] shadow-[0_0_24px_rgba(245,194,75,.12)] disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-white/[.035] disabled:text-[var(--muted)] disabled:shadow-none"
              onClick={submit}
              disabled={!canRun}
            >
              Run council
            </button>
            {onScout ? (
              <button
                type="button"
                className="focus-ring min-h-12 rounded-2xl border border-[var(--aurora-teal)]/45 bg-[var(--aurora-teal)]/10 px-5 font-display text-sm font-semibold text-[var(--text)] disabled:cursor-wait disabled:border-white/10 disabled:bg-white/[.035] disabled:text-[var(--muted)]"
                onClick={onScout}
                disabled={scoutStatus === "loading"}
            >
                {scoutStatus === "loading" ? "Scouting..." : "Run Alpha Scout discovery"}
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-2" aria-label="Model roster">
          {roster.map((model) => {
            const enabled = Boolean(enabledById[model.model_id]);
            return (
              <button
                key={model.model_id}
                type="button"
                aria-pressed={enabled}
                className={`focus-ring rounded-full border px-3 py-2 text-left text-xs transition ${
                  enabled
                    ? "border-[var(--aurora-teal)]/45 bg-[var(--aurora-teal)]/10 text-[var(--text)]"
                    : "border-white/10 bg-white/[.025] text-[var(--muted)]"
                }`}
                onClick={() => toggleModel(model.model_id)}
              >
                <span className="font-medium">{model.label}</span>
                <span className="data-text ml-2 opacity-70">{model.provider}</span>
              </button>
            );
          })}
        </div>
        <div className="data-text text-xs text-[var(--muted)]" aria-live="polite">
          {status} · {new Date().toLocaleDateString(undefined, { month: "short", day: "2-digit", year: "numeric" })}
        </div>
      </div>
    </section>
  );
}
