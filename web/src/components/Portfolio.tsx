import type { PortfolioSnapshot, Rating } from "../api/types";
import { AllocationDonut } from "./AllocationDonut";

const ratingClasses: Record<Rating, string> = {
  Buy: "text-[var(--rate-buy)]",
  Overweight: "text-[var(--rate-overweight)]",
  Hold: "text-[var(--rate-hold)]",
  Underweight: "text-[var(--rate-underweight)]",
  Sell: "text-[var(--rate-sell)]"
};

export function PortfolioPanel({ snapshot }: { snapshot?: PortfolioSnapshot }) {
  if (!snapshot || snapshot.positions.length === 0) {
    return (
      <section className="glass min-h-56 p-5" aria-labelledby="portfolio-title">
        <p className="data-text text-xs uppercase text-[var(--muted)]">Portfolio</p>
        <h2 id="portfolio-title" className="mt-2 font-display text-2xl font-semibold">
          No portfolio loaded
        </h2>
        <p className="mt-4 text-sm leading-6 text-[var(--muted)]">
          Allocation and concentration checks connect once holdings are available.
        </p>
      </section>
    );
  }

  return (
    <section className="glass min-h-56 p-5" aria-labelledby="portfolio-title">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <AllocationDonut positions={snapshot.positions} />
        <div className="min-w-0 flex-1">
          <p className="data-text text-xs uppercase text-[var(--muted)]">Portfolio</p>
          <h2 id="portfolio-title" className="mt-2 font-display text-2xl font-semibold">
            Allocation map
          </h2>

          {snapshot.concentration_flag ? (
            <div className="mt-4 rounded-2xl border border-[var(--rate-sell)]/35 bg-[var(--rate-sell)]/10 p-3 text-sm leading-6">
              Concentration flag: top holding {snapshot.top_holding_pct.toFixed(1)}%, top three{" "}
              {snapshot.top3_pct.toFixed(1)}%.
            </div>
          ) : null}

          <ul className="mt-5 space-y-2" aria-label="Portfolio positions">
            {snapshot.positions.map((position) => (
              <li
                key={position.ticker}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-white/10 bg-white/[.03] px-3 py-2"
              >
                <span className="data-text truncate text-sm text-[var(--text)]">{position.ticker}</span>
                <span className="data-text text-xs text-[var(--muted)]">
                  {position.rating ? (
                    <span className={ratingClasses[position.rating]}>{position.rating}</span>
                  ) : null}{" "}
                  {position.weight_pct.toFixed(1)}%
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
