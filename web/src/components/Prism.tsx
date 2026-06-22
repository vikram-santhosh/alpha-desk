export function Prism({ resolved }: { resolved: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 280 160"
      className={`mx-auto h-36 w-full max-w-sm ${resolved ? "prism-resolved" : ""}`}
    >
      <defs>
        <linearGradient id="beam-gradient" x1="0" x2="1" y1="0" y2="0">
          <stop stopColor="var(--aurora-indigo)" />
          <stop offset=".52" stopColor="var(--aurora-teal)" />
          <stop offset="1" stopColor="var(--aurora-violet)" />
        </linearGradient>
      </defs>
      <path d="M18 80H88" stroke="rgba(234,238,250,.7)" strokeWidth="3" strokeLinecap="round" />
      <path
        d="M96 132L136 28l50 104H96z"
        fill="rgba(255,255,255,.06)"
        stroke="rgba(255,255,255,.35)"
        strokeWidth="2"
      />
      <path className="spectral-ray ray-a" d="M153 68L260 22" stroke="var(--aurora-indigo)" strokeWidth="3" />
      <path className="spectral-ray ray-b" d="M158 82L260 80" stroke="var(--aurora-teal)" strokeWidth="3" />
      <path className="spectral-ray ray-c" d="M153 96L260 136" stroke="var(--aurora-violet)" strokeWidth="3" />
      <path
        className="recombined-ray"
        d="M186 82H262"
        stroke="url(#beam-gradient)"
        strokeWidth="6"
        strokeLinecap="round"
        opacity={resolved ? ".95" : ".25"}
      />
    </svg>
  );
}
