import type { JudgeAnalysis } from "../api/types";

function Group({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h4 className="data-text text-xs uppercase text-[var(--muted)]">{title}</h4>
      <ul className="mt-3 space-y-2">
        {items.length ? (
          items.map((item, index) => (
            <li
              key={`${title}-${index}-${item}`}
              className="rounded-xl border border-white/10 bg-white/[.03] px-3 py-2 text-sm leading-6"
            >
              {item}
            </li>
          ))
        ) : (
          <li className="text-sm text-[var(--muted)]">No entries yet.</li>
        )}
      </ul>
    </section>
  );
}

export function JudgePanel({ judge }: { judge?: JudgeAnalysis }) {
  return (
    <aside className="rounded-2xl border border-white/10 bg-white/[.035] p-5" aria-label="Council judge analysis">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="data-text text-xs uppercase text-[var(--muted)]">Council judge</p>
          <h3 className="mt-2 font-display text-2xl font-semibold">Recombined signal</h3>
        </div>
        <span className="data-text rounded-full border border-[var(--aurora-teal)]/35 px-3 py-1 text-xs text-[var(--aurora-teal)]">
          judge
        </span>
      </div>

      {judge?.crowded_narrative_flag ? (
        <div className="mt-5 rounded-2xl border border-[var(--rate-underweight)]/40 bg-[var(--rate-underweight)]/10 p-4 text-sm leading-6 text-[var(--text)]">
          <strong className="font-semibold">Consensus rests on a crowded narrative — confidence adjusted down.</strong>
          <p className="mt-1 text-[var(--muted)]">
            {judge.crowded_narrative_flag.topic}: {judge.crowded_narrative_flag.note}
          </p>
        </div>
      ) : null}

      <div className="mt-6 grid gap-5">
        <Group title="Consensus" items={judge?.consensus ?? []} />
        <Group title="Contradictions" items={judge?.contradictions ?? []} />
        <Group title="Blind spots" items={judge?.blind_spots ?? []} />
      </div>
    </aside>
  );
}
