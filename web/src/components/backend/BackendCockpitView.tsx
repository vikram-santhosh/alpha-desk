import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { BrainCircuit, DatabaseZap, Globe, Rocket, Wallet } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { ElementType } from "react";
import { API_BASE_URL, fetchCouncilModels, fetchMacroRegime, fetchPortfolioSnapshot } from "@/lib/api";
import { rise, stagger } from "@/lib/motion";
import type { MacroRegime, ModelOption, PortfolioSnapshot } from "@/types";
import { GlassButton } from "@/components/ui/GlassButton";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusBadge } from "@/components/ui/StatusBadge";

type EndpointState = "checking" | "live" | "offline" | "ready";

interface FeatureCardProps {
  title: string;
  endpoint: string;
  detail: string;
  state: EndpointState;
  icon: ElementType;
  action: string;
  onClick: () => void;
}

function FeatureCard({ title, endpoint, detail, state, icon: Icon, action, onClick }: FeatureCardProps) {
  return (
    <GlassCard className="p-5" hoverLift={false}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-(--color-border-subtle) bg-(--color-surface-elevated)/60 text-(--color-accent-cyan)">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-(--color-text-primary)">{title}</h2>
            <p className="truncate font-mono text-xs text-(--color-text-tertiary)">{endpoint}</p>
          </div>
        </div>
        <StatusBadge variant={state === "live" ? "success" : state === "offline" ? "critical" : "info"}>
          {state === "checking" ? "Checking" : state === "ready" ? "Ready" : state}
        </StatusBadge>
      </div>
      <p className="mt-4 min-h-16 text-sm leading-relaxed text-(--color-text-secondary)">{detail}</p>
      <GlassButton className="mt-5 w-full" variant="ghost" onClick={onClick}>
        {action}
      </GlassButton>
    </GlassCard>
  );
}

export default function BackendCockpitView() {
  const reduceMotion = useReducedMotion();
  const navigate = useNavigate();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [macro, setMacro] = useState<MacroRegime | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null);
  const [states, setStates] = useState<Record<string, EndpointState>>({
    council: "checking",
    scout: "checking",
    macro: "checking",
    portfolio: "checking",
  });
  const backendReady = Object.values(states).every((state) => state === "live" || state === "ready");

  useEffect(() => {
    let cancelled = false;
    const setState = (key: string, state: EndpointState) => {
      if (!cancelled) setStates((current) => ({ ...current, [key]: state }));
    };

    fetchCouncilModels()
      .then((data) => {
        if (!cancelled) setModels(data);
        setState("council", "live");
      })
      .catch(() => setState("council", "offline"));

    fetchMacroRegime()
      .then((data) => {
        if (!cancelled) setMacro(data);
        setState("macro", "live");
      })
      .catch(() => setState("macro", "offline"));

    fetchPortfolioSnapshot()
      .then((data) => {
        if (!cancelled) setPortfolio(data);
        setState("portfolio", "live");
      })
      .catch(() => setState("portfolio", "offline"));

    setState("scout", "ready");

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <motion.div
      className="mx-auto max-w-7xl space-y-6"
      variants={stagger}
      initial={reduceMotion ? "visible" : "hidden"}
      animate="visible"
    >
      <motion.header variants={rise}>
        <div className="flex items-center gap-2">
          <DatabaseZap className="h-5 w-5 text-(--color-accent-cyan)" />
          <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">Backend Cockpit</h1>
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-(--color-text-secondary)">
          This is the merged AlphaDesk UI: the 5173 dashboard theme, trimmed to pages that call the FastAPI backend at{" "}
          <span className="font-mono text-(--color-text-primary)">{API_BASE_URL}</span>.
        </p>
      </motion.header>

      <motion.div variants={rise} className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <FeatureCard
          title="Alpha Scout"
          endpoint="/api/ideas/today"
          detail="Runs discovery or top-buy idea generation through the backend Alpha Scout pipeline."
          state={states.scout}
          icon={Rocket}
          action="Open Alpha Scout"
          onClick={() => navigate("/scout")}
        />
        <FeatureCard
          title="Model Council"
          endpoint="/api/council/stream"
          detail={`${models.length || 0} backend model options loaded. Streams panel, judge, and verdict events.`}
          state={states.council}
          icon={BrainCircuit}
          action="Open Council"
          onClick={() => navigate("/council")}
        />
        <FeatureCard
          title="Macro Regime"
          endpoint="/api/macro"
          detail={macro ? `${macro.call} with ${macro.confidence}% confidence.` : "Fetches backend macro indicators and configured theses."}
          state={states.macro}
          icon={Globe}
          action="Open Macro"
          onClick={() => navigate("/macro")}
        />
        <FeatureCard
          title="Portfolio"
          endpoint="/api/portfolio"
          detail={portfolio ? `${portfolio.positions.length} positions. Top holding ${portfolio.top_holding_pct.toFixed(1)}%.` : "Reads configured backend holdings and concentration flags."}
          state={states.portfolio}
          icon={Wallet}
          action="Open Portfolio"
          onClick={() => navigate("/portfolio")}
        />
      </motion.div>

      <motion.div variants={rise}>
        <GlassCard className="p-5" glow={backendReady ? "emerald" : "amber"} hoverLift={false}>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-(--color-text-primary)">Backend truth check</h2>
              <p className="mt-1 text-sm text-(--color-text-secondary)">
                If a card says offline, the frontend is not falling back to local mock data. Start FastAPI and refresh.
              </p>
            </div>
            <StatusBadge variant={backendReady ? "success" : "warning"}>
              {backendReady ? "Backend ready" : "Backend incomplete"}
            </StatusBadge>
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
