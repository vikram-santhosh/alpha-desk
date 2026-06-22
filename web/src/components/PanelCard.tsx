import type { PanelVerdict, Rating } from "../api/types";

const ratingClasses: Record<Rating, string> = {
  Buy: "border-[var(--rate-buy)]/40 bg-[var(--rate-buy)]/10 text-[var(--rate-buy)]",
  Overweight: "border-[var(--rate-overweight)]/40 bg-[var(--rate-overweight)]/10 text-[var(--rate-overweight)]",
  Hold: "border-[var(--rate-hold)]/40 bg-[var(--rate-hold)]/10 text-[var(--rate-hold)]",
  Underweight: "border-[var(--rate-underweight)]/40 bg-[var(--rate-underweight)]/10 text-[var(--rate-underweight)]",
  Sell: "border-[var(--rate-sell)]/40 bg-[var(--rate-sell)]/10 text-[var(--rate-sell)]"
};

function modelLabelFromId(modelId: string) {
  return modelId
    .split("/")
    .pop()
    ?.replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase()) ?? modelId;
}

function ClaimList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <p className="data-text text-[0.62rem] text-[var(--muted)]">{title}</p>
      <ul className="mt-1 space-y-1">
        {items.slice(0, 3).map((item) => (
          <li key={item} className="rounded-lg border border-white/10 bg-white/[.035] px-2.5 py-1.5 text-xs leading-5 text-[var(--text)]/80">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PanelCard({ modelId, verdict }: { modelId: string; verdict?: PanelVerdict }) {
  const displayLabel = verdict?.label ?? modelLabelFromId(modelId);
  const resolved = Boolean(verdict);

  return (
    <article
      data-testid="panel-card"
      data-resolved={resolved ? "true" : "false"}
      className={`rounded-2xl border bg-white/[.035] p-4 transition ${
        verdict?.dissent
          ? "dissent border-[var(--aurora-violet)]/70 shadow-[0_0_36px_rgba(139,92,246,.22)]"
          : "border-white/10"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-display text-lg font-semibold">{displayLabel}</h3>
          <p className="data-text mt-1 truncate text-[0.68rem] text-[var(--muted)]">
            {verdict?.model_id ?? modelId}
          </p>
        </div>
        {verdict?.dissent ? (
          <span className="rounded-full border border-[var(--aurora-violet)]/50 bg-[var(--aurora-violet)]/10 px-2 py-1 text-[0.64rem] font-semibold uppercase text-[var(--aurora-violet)]">
            dissent
          </span>
        ) : null}
      </div>

      {verdict ? (
        <div className="mt-5">
          <div className="flex items-center justify-between gap-3">
            <span className={`data-text rounded-full border px-2.5 py-1 text-xs ${ratingClasses[verdict.rating]}`}>
              {verdict.rating}
            </span>
            <span className="data-text text-xs text-[var(--muted)]">
              {Math.round(verdict.confidence * 100)}%
            </span>
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10" aria-label="Confidence">
            <div
              className="h-full rounded-full bg-gradient-to-r from-[var(--aurora-indigo)] via-[var(--aurora-teal)] to-[var(--aurora-violet)] transition-[width] duration-700"
              style={{ width: `${Math.max(0, Math.min(verdict.confidence, 1)) * 100}%` }}
            />
          </div>
          <p className="mt-4 text-sm leading-6 text-[var(--text)]/90">{verdict.thesis}</p>
          <div className="mt-4 grid gap-3">
            <ClaimList title="Accepts" items={verdict.accepted_claims} />
            <ClaimList title="Rejects" items={verdict.rejected_claims} />
            <ClaimList title="Challenges" items={verdict.challenges} />
          </div>
        </div>
      ) : (
        <div className="mt-5 space-y-3" aria-label={`${displayLabel} thinking`}>
          <div className="thinking-shimmer h-6 w-28 rounded-full bg-white/10" />
          <div className="thinking-shimmer h-2 w-full rounded-full bg-white/10" />
          <div className="thinking-shimmer h-2 w-4/5 rounded-full bg-white/10" />
        </div>
      )}
    </article>
  );
}
