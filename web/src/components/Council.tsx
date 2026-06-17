import type { CouncilEvent, JudgeAnalysis, PanelVerdict, Verdict } from "../api/types";
import { JudgePanel } from "./JudgePanel";
import { PanelCard } from "./PanelCard";
import { Prism } from "./Prism";

type CouncilState = {
  ticker?: string;
  models: string[];
  panel: PanelVerdict[];
  judge?: JudgeAnalysis;
  verdict?: Verdict;
  error?: string;
};

function reduceEvents(events: CouncilEvent[]): CouncilState {
  return events.reduce<CouncilState>(
    (state, event) => {
      if (event.type === "panel_started") {
        return { ...state, ticker: event.data.ticker, models: event.data.models, error: undefined };
      }
      if (event.type === "panel_model_result") {
        const nextPanel = state.panel.filter((item) => item.model_id !== event.data.model_id);
        return { ...state, panel: [...nextPanel, event.data] };
      }
      if (event.type === "judge_result") {
        return { ...state, judge: event.data };
      }
      if (event.type === "verdict") {
        return { ...state, verdict: event.data };
      }
      if (event.type === "error") {
        return { ...state, error: event.data.message };
      }
      return state;
    },
    { models: [], panel: [] }
  );
}

function uniqueModels(state: CouncilState) {
  const modelSet = new Set(state.models);
  state.panel.forEach((item) => modelSet.add(item.model_id));
  return Array.from(modelSet);
}

export function Council({ events = [] }: { events?: CouncilEvent[] }) {
  const state = reduceEvents(events);
  const models = uniqueModels(state);
  const hasRun = events.length > 0;
  const panelByModel = new Map(state.panel.map((item) => [item.model_id, item]));

  return (
    <section className="glass min-h-[28rem] p-5 md:p-7" aria-labelledby="council-title">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="data-text text-xs uppercase text-[var(--muted)]">The council</p>
          <h2 id="council-title" className="font-display text-2xl font-semibold">
            Prism deliberation
          </h2>
        </div>
        <div className="data-text rounded-full border border-white/10 px-4 py-2 text-xs text-[var(--muted)]">
          {state.verdict ? `${state.verdict.ticker} resolved` : hasRun ? "Deliberating" : "Awaiting SSE"}
        </div>
      </div>

      {state.error ? (
        <div className="mt-5 rounded-2xl border border-[var(--rate-sell)]/40 bg-[var(--rate-sell)]/10 p-4 text-sm">
          {state.error}
        </div>
      ) : null}

      {!hasRun ? (
        <div className="mt-12 rounded-2xl border border-white/10 bg-white/[.03] p-6 text-sm leading-6 text-[var(--muted)]">
          No run yet — enter a ticker or idea and run the council.
        </div>
      ) : (
        <div className="mt-8 grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(14rem,.35fr)_minmax(0,.9fr)] xl:items-start">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-1">
            {models.map((modelId) => (
              <PanelCard key={modelId} modelId={modelId} verdict={panelByModel.get(modelId)} />
            ))}
          </div>
          <Prism resolved={Boolean(state.verdict)} />
          <JudgePanel judge={state.judge} />
        </div>
      )}
    </section>
  );
}
