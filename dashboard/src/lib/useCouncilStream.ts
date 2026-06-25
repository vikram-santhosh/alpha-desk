import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { councilStreamUrl, fetchLatestCouncilRun } from "@/lib/api";
import type {
  CouncilEvent,
  CouncilResult,
  CouncilRunRequest,
  DoneEvent,
  JudgeAnalysis,
  PanelVerdict,
  Verdict,
} from "@/types";

type StreamStatus = "idle" | "loading" | "complete" | "error";

export interface CouncilStreamState {
  status: StreamStatus;
  events: CouncilEvent[];
  error?: string;
  done?: DoneEvent;
  verdict?: Verdict;
  activeRun?: CouncilRunRequest;
  runCouncil: (request: CouncilRunRequest) => void;
  retry: () => void;
}

function parseEventData<T>(event: Event): T {
  const data = "data" in event && typeof event.data === "string" ? event.data : "{}";
  return JSON.parse(data) as T;
}

function findVerdict(events: CouncilEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type === "verdict") return event.data;
  }
  return undefined;
}

function findDone(events: CouncilEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type === "done") return event.data;
  }
  return undefined;
}

function eventsFromSavedRun(result: CouncilResult): CouncilEvent[] {
  const models = result.panel.map((item) => item.model_id);
  return [
    { type: "panel_started", data: { ticker: result.verdict.ticker, models } },
    ...result.panel.map((item) => ({ type: "panel_model_result" as const, data: item })),
    { type: "judge_result", data: result.judge },
    { type: "verdict", data: result.verdict },
    {
      type: "done",
      data: {
        cost_usd: result.cost_usd,
        degraded_reasons: result.degraded_reasons,
        council_mode: result.execution_mode,
        run_id: result.run_id,
        saved_at: result.saved_at,
      },
    },
  ];
}

export function useCouncilStream(): CouncilStreamState {
  const sourceRef = useRef<EventSource | null>(null);
  const lastRequestRef = useRef<CouncilRunRequest | null>(null);
  const lastCompletedEventsRef = useRef<CouncilEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [events, setEvents] = useState<CouncilEvent[]>([]);
  const [error, setError] = useState<string>();
  const [activeRun, setActiveRun] = useState<CouncilRunRequest>();

  const closeStream = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  const pushEvent = useCallback((event: CouncilEvent) => {
    setEvents((current) => [...current, event]);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchLatestCouncilRun()
      .then((result) => {
        if (cancelled || !result || sourceRef.current) return;
        const savedEvents = eventsFromSavedRun(result);
        lastCompletedEventsRef.current = savedEvents;
        lastRequestRef.current = {
          ticker: result.verdict.ticker,
          models: result.panel.map((item) => item.model_id),
        };
        setEvents(savedEvents);
        setActiveRun(undefined);
        setStatus("complete");
        setError(undefined);
      })
      .catch(() => {
        if (!cancelled) {
          setStatus((current) => (current === "idle" ? "idle" : current));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const runCouncil = useCallback(
    (request: CouncilRunRequest) => {
      closeStream();
      lastRequestRef.current = request;
      setStatus("loading");
      setError(undefined);
      setActiveRun(request);
      setEvents([]);

      const source = new EventSource(councilStreamUrl(request));
      sourceRef.current = source;

      source.addEventListener("panel_started", (event) => {
        pushEvent({ type: "panel_started", data: parseEventData<{ ticker: string; models: string[] }>(event) });
      });
      source.addEventListener("panel_model_result", (event) => {
        pushEvent({ type: "panel_model_result", data: parseEventData<PanelVerdict>(event) });
      });
      source.addEventListener("judge_result", (event) => {
        pushEvent({ type: "judge_result", data: parseEventData<JudgeAnalysis>(event) });
      });
      source.addEventListener("verdict", (event) => {
        pushEvent({ type: "verdict", data: parseEventData<Verdict>(event) });
      });
      source.addEventListener("done", (event) => {
        const doneEvent: CouncilEvent = { type: "done", data: parseEventData<DoneEvent>(event) };
        setEvents((current) => {
          const nextEvents = [...current, doneEvent];
          lastCompletedEventsRef.current = nextEvents;
          return nextEvents;
        });
        setStatus("complete");
        closeStream();
      });
      source.addEventListener("error", () => {
        const message = "Council stream failed. Confirm FastAPI is running at the configured backend URL.";
        setError(message);
        setStatus("error");
        setEvents((current) =>
          lastCompletedEventsRef.current.length > 0
            ? lastCompletedEventsRef.current
            : [...current, { type: "error", data: { message } }]
        );
        closeStream();
      });
    },
    [closeStream, pushEvent]
  );

  const retry = useCallback(() => {
    if (lastRequestRef.current) {
      runCouncil(lastRequestRef.current);
    }
  }, [runCouncil]);

  return useMemo(
    () => ({
      status,
      events,
      error,
      done: findDone(events),
      verdict: findVerdict(events),
      activeRun,
      runCouncil,
      retry,
    }),
    [activeRun, error, events, retry, runCouncil, status]
  );
}
