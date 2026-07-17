import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Bug, RefreshCw, Zap } from "lucide-react";
import type { BackendTopIdea, IdeaScoutResult, ScoutProgress } from "@/types";
import { fetchFastTopBuys, fetchIdeaScout, fetchLatestIdeaScout, fetchScoutProgress } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassButton } from "@/components/ui/GlassButton";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { IdeaCard } from "./IdeaCard";
import { ScoutPipeline } from "./ScoutPipeline";
import { IdeaDebugPanel } from "./IdeaDebugPanel";
import { useReducedMotion } from "@/lib/useReducedMotion";

export default function TopBuysView() {
  const [ideas, setIdeas] = useState<BackendTopIdea[]>([]);
  const [loading, setLoading] = useState(false);
  const [hydrating, setHydrating] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"top_buys" | "new_discoveries">("top_buys");
  const [progress, setProgress] = useState<ScoutProgress | null>(null);
  const [debugMode, setDebugMode] = useState(false);
  const reducedMotion = useReducedMotion();
  const pollRef = useRef<number | null>(null);

  const apply = useCallback((data: IdeaScoutResult) => {
    setIdeas([...data.ideas].sort((a, b) => a.rank - b.rank));
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    const tick = () => {
      fetchScoutProgress().then(setProgress).catch(() => {});
    };
    tick();
    pollRef.current = window.setInterval(tick, 700);
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // Show the last saved run for the active mode immediately — no click required.
  useEffect(() => {
    let active = true;
    setHydrating(true);
    setIdeas([]);
    fetchLatestIdeaScout(mode)
      .then((data) => { if (active && data) apply(data); })
      .catch(() => { /* first-run: nothing saved yet, that's fine */ })
      .finally(() => { if (active) setHydrating(false); });
    return () => { active = false; };
  }, [apply, mode]);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    startPolling();
    try {
      apply(await fetchIdeaScout(mode, 10));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load ideas");
    } finally {
      setLoading(false);
      stopPolling();
      fetchScoutProgress().then(setProgress).catch(() => {}); // capture final stage state
    }
  }, [apply, mode, startPolling, stopPolling]);

  const runFast = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      apply(await fetchFastTopBuys(10));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load fast top buys");
    } finally {
      setLoading(false);
    }
  }, [apply]);

  const showSkeleton = (hydrating || loading) && ideas.length === 0;

  return (
    <section className="mx-auto max-w-5xl space-y-6">
      <motion.header
        className="flex items-center justify-between gap-4"
        initial={reducedMotion ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">
            {mode === "top_buys" ? "Top Buys" : "New Discoveries"}
          </h1>
          <p className="mt-1 text-sm text-(--color-text-secondary)">
            {mode === "top_buys"
              ? "Highest-conviction names right now."
              : "Fresh ideas the scout surfaced beyond your current book."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SegmentedControl
            options={[
              { value: "top_buys", label: "Top Buys" },
              { value: "new_discoveries", label: "Discoveries" },
            ]}
            value={mode}
            onChange={(value) => setMode(value as "top_buys" | "new_discoveries")}
          />
          <GlassButton
            variant={debugMode ? "solid" : "ghost"}
            leftIcon={<Bug className="h-4 w-4" />}
            onClick={() => setDebugMode((v) => !v)}
            title="Show why each idea scored and ranked the way it did"
          >
            Debug
          </GlassButton>
          {mode === "top_buys" && (
            <GlassButton
              variant="ghost"
              leftIcon={<Zap className="h-4 w-4" />}
              onClick={() => void runFast()}
              disabled={loading}
              title="Instant deterministic ranking from the score engine (no LLM)"
            >
              Fast
            </GlassButton>
          )}
          <GlassButton
            variant="solid"
            leftIcon={<RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />}
            onClick={() => void run()}
            disabled={loading}
          >
            {loading ? "Finding…" : mode === "top_buys" ? "Get top buys" : "Find ideas"}
          </GlassButton>
        </div>
      </motion.header>

      <AnimatePresence>
        {(loading || progress?.active) && progress && (
          <ScoutPipeline progress={progress} />
        )}
      </AnimatePresence>

      {showSkeleton ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-64" />)}
        </div>
      ) : error && ideas.length === 0 ? (
        <GlassCard glow="rose" className="p-6">
          <EmptyState title={mode === "top_buys" ? "Couldn’t load top buys" : "Couldn’t load discoveries"} description={error}
            action={{ label: "Try again", onClick: () => void run() }} />
        </GlassCard>
      ) : ideas.length === 0 ? (
        <GlassCard className="p-8" hoverLift={false}>
          <EmptyState
            title={mode === "top_buys" ? "No top buys yet" : "No discoveries yet"}
            description={mode === "top_buys" ? "Press “Get top buys” to run the ranking." : "Press “Find ideas” to scout new names."}
            action={{ label: mode === "top_buys" ? "Get top buys" : "Find ideas", onClick: () => void run() }}
          />
        </GlassCard>
      ) : (
        <div className="grid items-start gap-4 sm:grid-cols-2">
          {ideas.map((idea, i) => (
            <div key={`${idea.ticker}-${idea.rank}`} className="flex flex-col">
              <IdeaCard idea={idea} index={i} />
              <AnimatePresence>
                {debugMode &&
                  (idea.debug ? (
                    <IdeaDebugPanel debug={idea.debug} />
                  ) : (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="mt-3 rounded-xl border border-dashed border-(--color-border-subtle) px-3 py-2 text-xs text-(--color-text-tertiary)"
                    >
                      No decision breakdown for this idea (run a fresh scout for full debug data).
                    </motion.div>
                  ))}
              </AnimatePresence>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
