import type { Scenario } from "../api/types";

const scenarioTone: Record<Scenario["name"], string> = {
  Bull: "bg-[var(--rate-buy)]",
  Base: "bg-[var(--aurora-teal)]",
  Bear: "bg-[var(--rate-sell)]"
};

function formatReturn(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

export function ScenarioBars({ scenarios }: { scenarios: Scenario[] }) {
  return (
    <div className="grid gap-3" aria-label="Scenario outcomes">
      {scenarios.map((scenario) => {
        const probability = Math.max(0, Math.min(scenario.probability, 1));
        const percent = Math.round(probability * 100);
        return (
          <div key={scenario.name}>
            <div className="mb-2 flex items-center justify-between gap-3">
              <span className="font-display text-sm font-semibold">{scenario.name}</span>
              <span className="data-text text-xs text-[var(--muted)]">
                {percent}% · {formatReturn(scenario.ret_pct)}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white/10">
              <div
                data-testid="scenario-bar"
                aria-label={`${scenario.name} probability ${percent}%`}
                className={`h-full rounded-full transition-[width] duration-700 ${scenarioTone[scenario.name]}`}
                style={{ width: `${percent}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
