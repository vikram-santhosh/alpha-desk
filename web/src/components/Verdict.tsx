import type { Rating, Verdict as VerdictPayload } from "../api/types";
import { ConvictionGauge } from "./ConvictionGauge";
import { ScenarioBars } from "./ScenarioBars";

const verdictRatingClasses: Record<Rating, string> = {
  Buy: "border-[var(--rate-buy)]/40 bg-[var(--rate-buy)]/10 text-[var(--rate-buy)]",
  Overweight: "border-[var(--rate-overweight)]/40 bg-[var(--rate-overweight)]/10 text-[var(--rate-overweight)]",
  Hold: "border-[var(--rate-hold)]/40 bg-[var(--rate-hold)]/10 text-[var(--rate-hold)]",
  Underweight: "border-[var(--rate-underweight)]/40 bg-[var(--rate-underweight)]/10 text-[var(--rate-underweight)]",
  Sell: "border-[var(--rate-sell)]/40 bg-[var(--rate-sell)]/10 text-[var(--rate-sell)]"
};

function InsightList({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h3 className="data-text text-xs uppercase text-[var(--muted)]">{title}</h3>
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <li key={item} className="rounded-xl border border-white/10 bg-white/[.03] px-3 py-2 text-sm leading-6">
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function VerdictPanel({ verdict }: { verdict?: VerdictPayload }) {
  if (!verdict) {
    return (
      <section className="glass min-h-56 p-5" aria-labelledby="verdict-title">
        <p className="data-text text-xs uppercase text-[var(--muted)]">Verdict</p>
        <h2 id="verdict-title" className="mt-2 font-display text-2xl font-semibold">
          Awaiting synthesis
        </h2>
        <p className="mt-4 max-w-xl text-sm leading-6 text-[var(--muted)]">
          The final rating, conviction gauge, scenarios, catalysts, and risks will crystallize here after
          the judge resolves the panel.
        </p>
      </section>
    );
  }

  return (
    <section
      className="glass min-h-56 border-[var(--gold)]/25 p-5 shadow-[0_24px_60px_-24px_rgba(245,194,75,.28)]"
      aria-labelledby="verdict-title"
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="data-text text-xs uppercase text-[var(--muted)]">Verdict</p>
          <h2 id="verdict-title" className="mt-2 font-display text-2xl font-semibold">
            {verdict.ticker} synthesis
          </h2>
        </div>
        <span className={`data-text rounded-full border px-3 py-1 text-sm ${verdictRatingClasses[verdict.rating]}`}>
          {verdict.rating}
        </span>
      </div>

      <div className="mt-6 grid gap-6 2xl:grid-cols-[.8fr_1fr]">
        <ConvictionGauge conviction={verdict.conviction} label={verdict.conviction_label} />
        <ScenarioBars scenarios={verdict.scenarios} />
      </div>

      <div className="mt-6 grid gap-5 md:grid-cols-2">
        <InsightList title="Catalysts" items={verdict.catalysts} />
        <InsightList title="Risks" items={verdict.risks} />
      </div>
    </section>
  );
}
