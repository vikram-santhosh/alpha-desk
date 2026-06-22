import type { MacroDashboard, MacroThemeStatus } from "../api/types";
import type { LoadStatus } from "./BackendFeatureGrid";

type MacroPanelProps = {
  dashboard?: MacroDashboard;
  error?: string;
  onRefresh: () => void;
  status: LoadStatus;
};

const themeClasses: Record<MacroThemeStatus, string> = {
  risk_on: "border-[var(--rate-buy)]/35 bg-[var(--rate-buy)]/10 text-[var(--rate-buy)]",
  neutral: "border-[var(--rate-hold)]/35 bg-[var(--rate-hold)]/10 text-[var(--rate-hold)]",
  risk_off: "border-[var(--rate-sell)]/35 bg-[var(--rate-sell)]/10 text-[var(--rate-sell)]"
};

function statusText(status: MacroThemeStatus) {
  if (status === "risk_on") return "Risk-on";
  if (status === "risk_off") return "Risk-off";
  return "Neutral";
}

export function MacroPanel({ dashboard, error, onRefresh, status }: MacroPanelProps) {
  const loading = status === "loading";

  return (
    <section id="macro" className="glass min-h-56 p-5" aria-labelledby="macro-title">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="data-text text-xs uppercase text-[var(--muted)]">Macro backend</p>
          <h2 id="macro-title" className="mt-2 font-display text-2xl font-semibold">
            Regime and theses
          </h2>
        </div>
        <button
          type="button"
          className="focus-ring min-h-10 rounded-2xl border border-[var(--aurora-teal)]/40 px-4 text-sm font-semibold text-[var(--aurora-teal)] disabled:cursor-wait disabled:border-white/10 disabled:text-[var(--muted)]"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {error ? (
        <div className="mt-5 rounded-2xl border border-[var(--rate-sell)]/40 bg-[var(--rate-sell)]/10 p-4 text-sm" role="alert">
          {error}
        </div>
      ) : null}

      {!dashboard && !error ? (
        <div className="mt-5 rounded-2xl border border-white/10 bg-white/[.03] p-4 text-sm leading-6 text-[var(--muted)]">
          {loading ? "Loading backend macro context..." : "Refresh macro to read the backend regime endpoint."}
        </div>
      ) : null}

      {dashboard ? (
        <>
          <div className="mt-5 grid gap-3 md:grid-cols-[.7fr_1fr]">
            <div className="rounded-2xl border border-white/10 bg-white/[.035] p-4">
              <p className="data-text text-xs uppercase text-[var(--muted)]">Regime</p>
              <p className="mt-2 font-display text-2xl font-semibold">{dashboard.regime.call}</p>
              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-xl border border-white/10 bg-white/[.03] p-3">
                  <p className="data-text text-[0.65rem] uppercase text-[var(--muted)]">Risk-on score</p>
                  <p className="data-text mt-1 text-lg text-[var(--aurora-teal)]">{dashboard.regime.score}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-white/[.03] p-3">
                  <p className="data-text text-[0.65rem] uppercase text-[var(--muted)]">Confidence</p>
                  <p className="data-text mt-1 text-lg text-[var(--gold)]">{dashboard.regime.confidence}</p>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[.035] p-4">
              <p className="data-text text-xs uppercase text-[var(--muted)]">{dashboard.regime.agent}</p>
              <p className="mt-2 text-sm leading-6 text-[var(--text)]/90">{dashboard.regime.rationale}</p>
              {dashboard.regime.sourceDetail ? (
                <p className="mt-3 text-xs leading-5 text-[var(--muted)]">{dashboard.regime.sourceDetail}</p>
              ) : null}
            </div>
          </div>

          {dashboard.degraded_reasons.length ? (
            <div className="mt-4 rounded-2xl border border-[var(--rate-underweight)]/40 bg-[var(--rate-underweight)]/10 p-4 text-sm leading-6">
              {dashboard.degraded_reasons.join(" ")}
            </div>
          ) : null}

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {dashboard.themes.map((theme) => (
              <article key={theme.id} className="rounded-2xl border border-white/10 bg-white/[.03] p-4">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-display text-base font-semibold">{theme.title}</h3>
                  <span className={`data-text shrink-0 rounded-full border px-2 py-1 text-[0.65rem] ${themeClasses[theme.status]}`}>
                    {statusText(theme.status)}
                  </span>
                </div>
                <ul className="mt-3 space-y-2">
                  {theme.bullets.map((bullet) => (
                    <li key={bullet} className="text-sm leading-6 text-[var(--muted)]">
                      {bullet}
                    </li>
                  ))}
                </ul>
                <p className="data-text mt-3 text-[0.65rem] uppercase text-[var(--muted)]">
                  {theme.agent} · {theme.confidence}% confidence · {theme.trend}
                </p>
              </article>
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}
