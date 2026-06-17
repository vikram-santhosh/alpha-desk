import { useEffect, useMemo, useState } from "react";

import { Council } from "./components/Council";

type NavItem = {
  label: string;
  active?: boolean;
};

const navItems: NavItem[] = [
  { label: "Cockpit", active: true },
  { label: "Briefs" },
  { label: "Portfolio" },
  { label: "Journal" }
];

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!media) return undefined;
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return reduced;
}

function PrismMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 64 64" className="h-10 w-10">
      <path
        d="M14 50L31 10l19 40H14z"
        fill="rgba(255,255,255,.06)"
        stroke="rgba(255,255,255,.42)"
        strokeWidth="2"
      />
      <path d="M2 31h20" stroke="var(--text)" strokeWidth="2" strokeLinecap="round" opacity=".82" />
      <path d="M39 30l20-11" stroke="var(--aurora-indigo)" strokeWidth="2" strokeLinecap="round" />
      <path d="M40 33l21 1" stroke="var(--aurora-teal)" strokeWidth="2" strokeLinecap="round" />
      <path d="M39 36l19 12" stroke="var(--aurora-violet)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function AuroraLayer({ reducedMotion }: { reducedMotion: boolean }) {
  const blobs = useMemo(
    () => [
      { className: "left-[8%] top-[2%] bg-[var(--aurora-indigo)] drift-a" },
      { className: "right-[10%] top-[6%] bg-[var(--aurora-teal)] drift-b" },
      { className: "bottom-[10%] left-[24%] bg-[var(--aurora-violet)] drift-c" },
      { className: "bottom-[2%] right-[18%] bg-[var(--aurora-indigo)] drift-d opacity-25" }
    ],
    []
  );

  return (
    <div aria-hidden="true" className="fixed inset-0 overflow-hidden">
      {blobs.map((blob) => {
        const className = reducedMotion
          ? blob.className.replace(/\s?drift-[a-d]/, "")
          : blob.className;
        return (
          <span
            key={blob.className}
            data-testid="aurora-blob"
            data-drift={reducedMotion ? "false" : "true"}
            className={`aurora-blob ${className}`}
          />
        );
      })}
      <div className="grain" />
    </div>
  );
}

function NavRail() {
  return (
    <aside
      aria-label="Primary"
      className="glass fixed left-4 top-4 z-20 hidden h-[calc(100vh-2rem)] w-24 flex-col items-center gap-8 px-3 py-5 lg:flex"
    >
      <PrismMark />
      <nav className="flex w-full flex-1 flex-col items-stretch gap-3">
        {navItems.map((item) => (
          <button
            key={item.label}
            type="button"
            className={`focus-ring rounded-2xl px-2 py-3 text-center text-[0.72rem] font-medium ${
              item.active
                ? "bg-white/10 text-[var(--text)]"
                : "nav-soon text-[var(--muted)] hover:text-[var(--text)]"
            }`}
            aria-current={item.active ? "page" : undefined}
            title={item.active ? item.label : `${item.label} soon`}
            disabled={!item.active}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <span className="data-text rotate-[-90deg] whitespace-nowrap text-[0.62rem] uppercase text-[var(--muted)]">
        local
      </span>
    </aside>
  );
}

function MobileTopBar() {
  return (
    <header className="glass mx-4 mt-4 flex items-center justify-between px-4 py-3 lg:hidden">
      <div className="flex items-center gap-3">
        <PrismMark />
        <span className="font-display text-lg font-bold">AlphaDesk</span>
      </div>
      <span className="data-text text-xs text-[var(--muted)]">Cockpit</span>
    </header>
  );
}

function CommandRegion() {
  return (
    <section className="glass flex flex-col gap-5 p-5 md:flex-row md:items-center md:justify-between">
      <div>
        <p className="data-text text-xs uppercase text-[var(--muted)]">Research cockpit</p>
        <h1 className="font-display text-3xl font-bold tracking-normal md:text-4xl">AlphaDesk</h1>
      </div>
      <div className="flex min-w-0 flex-col gap-2 text-left md:text-right">
        <p className="data-text text-sm text-[var(--text)]">No run yet</p>
        <p className="text-sm text-[var(--muted)]">Enter a ticker or idea and run the council.</p>
      </div>
    </section>
  );
}

function LowerCards() {
  return (
    <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
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
      <section className="glass min-h-56 p-5" aria-labelledby="portfolio-title">
        <p className="data-text text-xs uppercase text-[var(--muted)]">Portfolio</p>
        <h2 id="portfolio-title" className="mt-2 font-display text-2xl font-semibold">
          No portfolio loaded
        </h2>
        <p className="mt-4 text-sm leading-6 text-[var(--muted)]">
          Allocation and concentration checks connect in the portfolio panel.
        </p>
      </section>
    </div>
  );
}

export default function App() {
  const reducedMotion = usePrefersReducedMotion();

  return (
    <div className="relative min-h-screen overflow-hidden bg-[var(--void)] text-[var(--text)]">
      <AuroraLayer reducedMotion={reducedMotion} />
      <NavRail />
      <MobileTopBar />
      <main className="relative z-10 mx-auto flex min-h-screen w-full max-w-[1500px] flex-col gap-5 px-4 py-4 lg:pl-32">
        <CommandRegion />
        <div className="cockpit-grid grid gap-5">
          <Council />
          <LowerCards />
        </div>
      </main>
    </div>
  );
}
