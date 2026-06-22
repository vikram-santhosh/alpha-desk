import type { MacroDashboard, PortfolioSnapshot } from "../api/types";

export type LoadStatus = "idle" | "loading" | "complete" | "error";
export type ScoutMode = "top_buys" | "new_discoveries";

type FeatureGridProps = {
  activeScoutMode?: ScoutMode;
  apiBaseUrl: string;
  macro?: MacroDashboard;
  macroStatus: LoadStatus;
  modelCount: number;
  onRefreshMacro: () => void;
  onRefreshPortfolio: () => void;
  onRunScout: (mode: ScoutMode) => void;
  portfolio?: PortfolioSnapshot;
  portfolioStatus: LoadStatus;
  scoutStatus: LoadStatus;
};

type FeatureCardProps = {
  title: string;
  endpoint: string;
  description: string;
  status: string;
  statusTone?: "ready" | "working" | "warn";
  actionLabel: string;
  disabled?: boolean;
  onAction: () => void;
};

function statusClass(tone: FeatureCardProps["statusTone"] = "ready") {
  if (tone === "working") return "border-[var(--aurora-teal)]/40 bg-[var(--aurora-teal)]/10 text-[var(--aurora-teal)]";
  if (tone === "warn") return "border-[var(--rate-underweight)]/40 bg-[var(--rate-underweight)]/10 text-[var(--rate-underweight)]";
  return "border-[var(--rate-buy)]/35 bg-[var(--rate-buy)]/10 text-[var(--rate-buy)]";
}

function FeatureCard({
  title,
  endpoint,
  description,
  status,
  statusTone,
  actionLabel,
  disabled,
  onAction
}: FeatureCardProps) {
  return (
    <article className="flex min-h-64 min-w-0 flex-col rounded-2xl border border-white/10 bg-white/[.035] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-display text-lg font-semibold">{title}</h3>
          <p className="data-text mt-2 truncate text-xs text-[var(--muted)]">{endpoint}</p>
        </div>
        <span className={`data-text shrink-0 rounded-full border px-2 py-1 text-[0.65rem] ${statusClass(statusTone)}`}>
          {status}
        </span>
      </div>
      <p className="mt-4 flex-1 text-sm leading-6 text-[var(--muted)]">{description}</p>
      <button
        type="button"
        className="focus-ring mt-5 min-h-11 rounded-2xl border border-[var(--aurora-teal)]/45 bg-[var(--aurora-teal)]/10 px-4 font-display text-sm font-semibold text-[var(--text)] disabled:cursor-wait disabled:border-white/10 disabled:bg-white/[.035] disabled:text-[var(--muted)]"
        disabled={disabled}
        onClick={onAction}
      >
        {actionLabel}
      </button>
    </article>
  );
}

function statusFor(status: LoadStatus, fallback: string) {
  if (status === "loading") return "Running";
  if (status === "complete") return "Live";
  if (status === "error") return "Error";
  return fallback;
}

function toneFor(status: LoadStatus): FeatureCardProps["statusTone"] {
  if (status === "loading") return "working";
  if (status === "error") return "warn";
  return "ready";
}

export function BackendFeatureGrid({
  activeScoutMode,
  apiBaseUrl,
  macro,
  macroStatus,
  modelCount,
  onRefreshMacro,
  onRefreshPortfolio,
  onRunScout,
  portfolio,
  portfolioStatus,
  scoutStatus
}: FeatureGridProps) {
  const scoutBusy = scoutStatus === "loading";
  const macroStatusText = macro?.regime.call ? `${macro.regime.call} · ${macro.regime.score}` : statusFor(macroStatus, "Ready");
  const portfolioStatusText = portfolio?.positions.length
    ? `${portfolio.positions.length} positions`
    : statusFor(portfolioStatus, "Ready");

  return (
    <section id="features" className="glass p-5 md:p-6" aria-labelledby="features-title">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="data-text text-xs uppercase text-[var(--muted)]">Backend feature map</p>
          <h2 id="features-title" className="mt-1 font-display text-2xl font-semibold">
            Explore live AlphaDesk systems
          </h2>
        </div>
        <div className="data-text rounded-full border border-white/10 px-3 py-2 text-xs text-[var(--muted)]">
          API {apiBaseUrl} · {modelCount} council models
        </div>
      </div>

      <div className="mt-5 grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <FeatureCard
          title="Alpha Scout discovery"
          endpoint="/api/ideas/today?mode=new_discoveries"
          description="Runs the full Alpha Scout discovery pipeline while excluding existing portfolio/watchlist tickers."
          status={activeScoutMode === "new_discoveries" ? statusFor(scoutStatus, "Ready") : "Ready"}
          statusTone={activeScoutMode === "new_discoveries" ? toneFor(scoutStatus) : "ready"}
          actionLabel={scoutBusy && activeScoutMode === "new_discoveries" ? "Running discovery..." : "Run discovery"}
          disabled={scoutBusy}
          onAction={() => onRunScout("new_discoveries")}
        />
        <FeatureCard
          title="Alpha Scout top buys"
          endpoint="/api/ideas/today?mode=top_buys"
          description="Runs the same backend screen with the current tracked universe included for buy-ranked candidates."
          status={activeScoutMode === "top_buys" ? statusFor(scoutStatus, "Ready") : "Ready"}
          statusTone={activeScoutMode === "top_buys" ? toneFor(scoutStatus) : "ready"}
          actionLabel={scoutBusy && activeScoutMode === "top_buys" ? "Running top buys..." : "Run top buys"}
          disabled={scoutBusy}
          onAction={() => onRunScout("top_buys")}
        />
        <FeatureCard
          title="Macro regime"
          endpoint="/api/macro"
          description="Fetches backend macro indicators, configured theses, regime score, confidence, and degradation notes."
          status={macroStatusText}
          statusTone={toneFor(macroStatus)}
          actionLabel={macroStatus === "loading" ? "Refreshing macro..." : "Refresh macro"}
          disabled={macroStatus === "loading"}
          onAction={onRefreshMacro}
        />
        <FeatureCard
          title="Portfolio context"
          endpoint="/api/portfolio"
          description="Loads configured holdings and concentration checks used as context for the council and scout."
          status={portfolioStatusText}
          statusTone={toneFor(portfolioStatus)}
          actionLabel={portfolioStatus === "loading" ? "Refreshing portfolio..." : "Refresh portfolio"}
          disabled={portfolioStatus === "loading"}
          onAction={onRefreshPortfolio}
        />
      </div>
    </section>
  );
}
