import type { DataSourceStatus, IdeaScoutResult, TopIdea } from "../api/types";

type IdeaScoutProps = {
  result?: IdeaScoutResult;
  status: "idle" | "loading" | "complete" | "error";
  error?: string;
  onRunIdea: (idea: TopIdea) => void;
};

function scoreLabel(score: number) {
  return `${Math.round(Math.max(0, Math.min(score, 1)) * 100)}`;
}

function modeLabel(mode?: string) {
  if (mode === "top_buys") return "Top buys";
  if (mode === "new_discoveries") return "New discoveries";
  if (mode === "openrouter") return "OpenRouter";
  if (mode === "mock") return "Mock";
  return "Unknown";
}

function titleForMode(mode?: string) {
  if (mode === "new_discoveries") return "Alpha Scout discoveries";
  if (mode === "top_buys") return "Alpha Scout top buys";
  return "Alpha Scout ideas";
}

function trackedChecks(result: IdeaScoutResult) {
  return Object.entries(result.audit?.tracked_ticker_checks ?? {}).slice(0, 18);
}

const sourceStatusCopy: Record<DataSourceStatus, string> = {
  validated: "Validated",
  configured: "Configured",
  unavailable: "Unavailable"
};

const sourceStatusClasses: Record<DataSourceStatus, string> = {
  validated: "border-[var(--rate-buy)]/40 bg-[var(--rate-buy)]/10 text-[var(--rate-buy)]",
  configured: "border-[var(--rate-underweight)]/40 bg-[var(--rate-underweight)]/10 text-[var(--rate-underweight)]",
  unavailable: "border-[var(--rate-sell)]/40 bg-[var(--rate-sell)]/10 text-[var(--rate-sell)]"
};

export function IdeaScout({ result, status, error, onRunIdea }: IdeaScoutProps) {
  if (status === "idle" && !result) return null;

  return (
    <section className="glass p-5" aria-labelledby="idea-scout-title">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="data-text text-xs uppercase text-[var(--muted)]">Alpha Scout pipeline</p>
          <h2 id="idea-scout-title" className="mt-1 font-display text-2xl font-semibold">
            {titleForMode(result?.scout_mode)}
          </h2>
        </div>
        <div className="data-text text-xs text-[var(--muted)]">
          {status === "loading" ? "Scanning..." : result ? `${result.ideas.length} ideas · ${result.as_of}` : "No ideas"}
        </div>
      </div>

      {status === "loading" ? (
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className="rounded-2xl border border-white/10 bg-white/[.03] p-4">
              <div className="thinking-shimmer h-5 w-20 rounded-full bg-white/10" />
              <div className="thinking-shimmer mt-4 h-3 w-full rounded-full bg-white/10" />
              <div className="thinking-shimmer mt-3 h-3 w-4/5 rounded-full bg-white/10" />
            </div>
          ))}
        </div>
      ) : null}

      {status === "error" ? (
        <div
          className="mt-5 rounded-2xl border border-[var(--rate-sell)]/40 bg-[var(--rate-sell)]/10 p-4 text-sm"
          role="alert"
        >
          {error ?? "Idea scout failed."}
        </div>
      ) : null}

      {result ? (
        <>
          <div className="mt-5 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <div className="rounded-2xl border border-white/10 bg-white/[.03] p-3">
              <p className="data-text text-xs uppercase text-[var(--muted)]">Pipeline mode</p>
              <p className="mt-2 font-display text-lg font-semibold">{modeLabel(result.scout_mode)}</p>
              <p className="mt-1 text-xs leading-5 text-[var(--muted)]">{result.universe}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[.03] p-3">
              <p className="data-text text-xs uppercase text-[var(--muted)]">Universe audit</p>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <span className="data-text rounded-full border border-white/10 px-2 py-1">
                  raw {result.audit?.raw_candidates ?? 0}
                </span>
                <span className="data-text rounded-full border border-white/10 px-2 py-1">
                  unique {result.audit?.unique_candidates ?? 0}
                </span>
                <span className="data-text rounded-full border border-white/10 px-2 py-1">
                  capped {result.audit?.capped_candidates ?? 0}
                </span>
                <span className="data-text rounded-full border border-white/10 px-2 py-1">
                  tracked {result.audit?.existing_universe_count ?? 0}
                </span>
              </div>
              {trackedChecks(result).length ? (
                <div className="mt-3 flex flex-wrap gap-2" aria-label="Tracked ticker inclusion">
                  {trackedChecks(result).map(([ticker, check]) => {
                    const included = check.included === true;
                    return (
                      <span
                        key={ticker}
                        className={`data-text rounded-full border px-2 py-1 text-[0.65rem] ${
                          included
                            ? "border-[var(--rate-buy)]/40 bg-[var(--rate-buy)]/10 text-[var(--rate-buy)]"
                            : "border-[var(--rate-sell)]/40 bg-[var(--rate-sell)]/10 text-[var(--rate-sell)]"
                        }`}
                        title={typeof check.source === "string" ? check.source : undefined}
                      >
                        {ticker} {included ? "included" : "missing"}
                      </span>
                    );
                  })}
                </div>
              ) : null}
            </div>
          </div>

          {result.degraded_reasons.length ? (
            <div className="mt-5 rounded-2xl border border-[var(--rate-underweight)]/40 bg-[var(--rate-underweight)]/10 p-4 text-sm leading-6">
              {result.degraded_reasons.join(" ")}
            </div>
          ) : null}

          {result.data_source_checks.length ? (
            <div className="mt-5" aria-label="Data source checks">
              <h3 className="data-text text-xs uppercase text-[var(--muted)]">Data source checks</h3>
              <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {result.data_source_checks.map((check) => (
                  <div
                    key={`${check.source}-${check.checked_at}`}
                    className="rounded-2xl border border-white/10 bg-white/[.03] p-3"
                    data-testid="source-check"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="font-display text-sm font-semibold">{check.source}</p>
                      <span className={`data-text rounded-full border px-2 py-1 text-[0.65rem] ${sourceStatusClasses[check.status]}`}>
                        {sourceStatusCopy[check.status]}
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-[var(--muted)]">{check.detail}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {result.ideas.map((idea) => (
              <article
                key={`${idea.rank}-${idea.ticker}`}
                className="rounded-2xl border border-white/10 bg-white/[.035] p-4"
                data-testid="idea-card"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="data-text text-xs text-[var(--muted)]">#{idea.rank}</p>
                    <h3 className="mt-1 truncate font-display text-lg font-semibold">
                      {idea.ticker} <span className="text-[var(--muted)]">{idea.company}</span>
                    </h3>
                  </div>
                  <span className="data-text rounded-full border border-[var(--aurora-teal)]/40 bg-[var(--aurora-teal)]/10 px-2.5 py-1 text-xs text-[var(--aurora-teal)]">
                    {scoreLabel(idea.score)}
                  </span>
                </div>

                <p className="data-text mt-3 text-xs uppercase text-[var(--muted)]">{idea.theme}</p>
                <p className="mt-3 text-sm leading-6 text-[var(--text)]/90">{idea.thesis}</p>
                <div className="mt-4 flex items-center justify-between gap-3">
                  <span className="data-text text-xs text-[var(--muted)]">{idea.horizon}</span>
                  <button
                    type="button"
                    className="focus-ring rounded-full border border-[var(--gold)]/55 bg-[var(--gold)]/10 px-3 py-2 text-xs font-semibold text-[var(--text)]"
                    onClick={() => onRunIdea(idea)}
                  >
                    Run council
                  </button>
                </div>
              </article>
            ))}
          </div>
          <p className="mt-4 text-xs leading-5 text-[var(--muted)]">{result.disclaimer}</p>
        </>
      ) : null}
    </section>
  );
}
