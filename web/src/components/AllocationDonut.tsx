import type { Position } from "../api/types";

const segmentColors = [
  "var(--aurora-indigo)",
  "var(--aurora-teal)",
  "var(--aurora-violet)",
  "var(--rate-buy)",
  "var(--rate-sell)",
  "var(--rate-hold)"
];

export function AllocationDonut({ positions }: { positions: Position[] }) {
  let offset = 0;

  return (
    <svg role="img" aria-label="Portfolio allocation" viewBox="0 0 180 180" className="h-44 w-44 shrink-0">
      <circle cx="90" cy="90" r="58" fill="none" stroke="rgba(255,255,255,.10)" strokeWidth="18" />
      {positions.map((position, index) => {
        const weight = Math.max(0, Math.min(position.weight_pct, 100));
        const segment = (
          <circle
            key={position.ticker}
            data-testid="allocation-segment"
            data-weight={weight}
            cx="90"
            cy="90"
            r="58"
            fill="none"
            pathLength={100}
            stroke={segmentColors[index % segmentColors.length]}
            strokeDasharray={`${weight} ${100 - weight}`}
            strokeDashoffset={-offset}
            strokeLinecap="butt"
            strokeWidth="18"
            transform="rotate(-90 90 90)"
          />
        );
        offset += weight;
        return segment;
      })}
      <text x="90" y="83" textAnchor="middle" className="fill-[var(--text)] font-mono text-lg font-semibold">
        {Math.round(positions.reduce((total, position) => total + position.weight_pct, 0))}%
      </text>
      <text x="90" y="104" textAnchor="middle" className="fill-[var(--muted)] font-mono text-[.62rem] uppercase">
        allocated
      </text>
    </svg>
  );
}
