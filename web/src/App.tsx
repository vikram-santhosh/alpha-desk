import { useEffect, useMemo, useState } from "react";

import type { ModelOption, PortfolioSnapshot, Verdict } from "./api/types";
import { fetchCouncilModels, fetchPortfolioSnapshot } from "./api/client";
import { useCouncilStream } from "./api/useCouncilStream";
import { CommandBar } from "./components/CommandBar";
import { Council } from "./components/Council";
import { PortfolioPanel } from "./components/Portfolio";
import { VerdictPanel } from "./components/Verdict";

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

const fallbackRoster: ModelOption[] = [
  { model_id: "anthropic/claude-opus-4.8", label: "Claude Opus 4.8", provider: "Anthropic", enabled: true },
  { model_id: "google/gemini-3.1-pro-preview", label: "Gemini 3.1 Pro", provider: "Google", enabled: true },
  { model_id: "x-ai/grok-4.3", label: "Grok 4.3", provider: "xAI", enabled: true }
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
            aria-disabled={item.active ? undefined : true}
            title={item.active ? item.label : `${item.label} soon`}
            onClick={(event) => {
              if (!item.active) event.preventDefault();
            }}
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

function LowerCards({
  portfolio,
  verdict
}: {
  portfolio?: PortfolioSnapshot;
  verdict?: Verdict;
}) {
  return (
    <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
      <VerdictPanel verdict={verdict} />
      <PortfolioPanel snapshot={portfolio} />
    </div>
  );
}

function runStatus({
  status,
  activeRun,
  done,
  error
}: Pick<ReturnType<typeof useCouncilStream>, "status" | "activeRun" | "done" | "error">) {
  if (status === "loading" && activeRun) return `Running ${activeRun.ticker}`;
  if (status === "complete") return done ? `Council complete · $${done.cost_usd.toFixed(2)}` : "Council complete";
  if (status === "error") return error ?? "Fusion call failed";
  return "No run yet";
}

export default function App() {
  const reducedMotion = usePrefersReducedMotion();
  const [roster, setRoster] = useState(fallbackRoster);
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot>();
  const councilStream = useCouncilStream();

  useEffect(() => {
    let cancelled = false;

    async function loadRoster() {
      try {
        const models = await fetchCouncilModels();
        if (!cancelled && models.length > 0) {
          setRoster(models);
        }
      } catch {
        // Local UI still works with the OpenRouter-compatible fallback roster.
      }
    }

    void loadRoster();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadPortfolio() {
      try {
        const snapshot = await fetchPortfolioSnapshot();
        if (!cancelled) {
          setPortfolio(snapshot);
        }
      } catch {
        // Keep the requested empty portfolio state when the local API is offline.
      }
    }

    void loadPortfolio();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="relative min-h-screen overflow-hidden bg-[var(--void)] text-[var(--text)]">
      <AuroraLayer reducedMotion={reducedMotion} />
      <NavRail />
      <MobileTopBar />
      <main
        className="relative z-10 mx-auto flex min-h-screen w-full max-w-[1500px] flex-col gap-5 px-4 py-4 lg:pl-32"
        aria-label="AlphaDesk research cockpit"
      >
        <CommandBar roster={roster} status={runStatus(councilStream)} onRun={councilStream.runCouncil} />
        {councilStream.error ? (
          <div
            className="glass flex flex-col gap-3 border-[var(--rate-sell)]/35 p-4 sm:flex-row sm:items-center sm:justify-between"
            role="alert"
          >
            <span className="text-sm text-[var(--text)]">{councilStream.error}</span>
            <button
              type="button"
              className="focus-ring rounded-2xl border border-[var(--aurora-teal)]/40 px-4 py-2 text-sm font-semibold text-[var(--aurora-teal)]"
              onClick={councilStream.retry}
            >
              Retry
            </button>
          </div>
        ) : null}
        <div className="cockpit-grid grid gap-5">
          <Council events={councilStream.events} />
          <LowerCards portfolio={portfolio} verdict={councilStream.verdict} />
        </div>
      </main>
    </div>
  );
}
