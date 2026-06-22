export function ConvictionGauge({ conviction, label }: { conviction: number; label: string }) {
  const clamped = Math.max(0, Math.min(conviction, 1));
  const percent = Math.round(clamped * 100);

  return (
    <div className="flex items-center gap-5">
      <svg
        role="meter"
        aria-label="Conviction"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        viewBox="0 0 160 104"
        className="h-28 w-40 shrink-0 overflow-visible"
      >
        <defs>
          <linearGradient id="conviction-gradient" x1="20" y1="90" x2="140" y2="20">
            <stop offset="0%" stopColor="var(--aurora-teal)" />
            <stop offset="100%" stopColor="var(--gold)" />
          </linearGradient>
          <filter id="conviction-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <path
          d="M24 86a56 56 0 0 1 112 0"
          fill="none"
          stroke="rgba(255,255,255,.12)"
          strokeLinecap="round"
          strokeWidth="14"
        />
        <path
          data-testid="conviction-arc"
          d="M24 86a56 56 0 0 1 112 0"
          fill="none"
          pathLength={100}
          stroke="url(#conviction-gradient)"
          strokeDasharray={`${percent} 100`}
          strokeLinecap="round"
          strokeWidth="14"
          filter="url(#conviction-glow)"
        />
        <text x="80" y="82" textAnchor="middle" className="fill-[var(--text)] font-mono text-[1.35rem] font-semibold">
          {percent}%
        </text>
      </svg>
      <div className="min-w-0">
        <p className="data-text text-xs uppercase text-[var(--muted)]">Conviction</p>
        <p className="mt-2 text-sm leading-6 text-[var(--text)]">{label}</p>
      </div>
    </div>
  );
}
