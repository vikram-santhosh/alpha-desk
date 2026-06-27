import { useCallback, useEffect, useState } from "react";
import { motion } from "motion/react";
import { RefreshCw } from "lucide-react";
import type { BackendTopIdea, IdeaScoutResult } from "@/types";
import { fetchIdeaScout, fetchLatestIdeaScout } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlassButton } from "@/components/ui/GlassButton";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { IdeaCard } from "./IdeaCard";
import { useReducedMotion } from "@/lib/useReducedMotion";

export default function TopBuysView() {
  const [ideas, setIdeas] = useState<BackendTopIdea[]>([]);
  const [loading, setLoading] = useState(false);
  const [hydrating, setHydrating] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reducedMotion = useReducedMotion();

  const apply = useCallback((data: IdeaScoutResult) => {
    setIdeas([...data.ideas].sort((a, b) => a.rank - b.rank));
  }, []);

  // Show the last saved run immediately — no clicking required to see something.
  useEffect(() => {
    let active = true;
    fetchLatestIdeaScout("top_buys")
      .then((data) => { if (active && data) apply(data); })
      .catch(() => { /* first-run: nothing saved yet, that's fine */ })
      .finally(() => { if (active) setHydrating(false); });
    return () => { active = false; };
  }, [apply]);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      apply(await fetchIdeaScout("top_buys", 10));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load top buys");
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
          <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">Top Buys</h1>
          <p className="mt-1 text-sm text-(--color-text-secondary)">Highest-conviction names right now.</p>
        </div>
        <GlassButton
          variant="solid"
          leftIcon={<RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />}
          onClick={() => void run()}
          disabled={loading}
        >
          {loading ? "Finding…" : "Get top buys"}
        </GlassButton>
      </motion.header>

      {showSkeleton ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-64" />)}
        </div>
      ) : error && ideas.length === 0 ? (
        <GlassCard glow="rose" className="p-6">
          <EmptyState title="Couldn’t load top buys" description={error}
            action={{ label: "Try again", onClick: () => void run() }} />
        </GlassCard>
      ) : ideas.length === 0 ? (
        <GlassCard className="p-8" hoverLift={false}>
          <EmptyState title="No top buys yet" description="Press “Get top buys” to run the ranking."
            action={{ label: "Get top buys", onClick: () => void run() }} />
        </GlassCard>
      ) : (
        <div className="grid items-stretch gap-4 sm:grid-cols-2">
          {ideas.map((idea, i) => (
            <IdeaCard key={`${idea.ticker}-${idea.rank}`} idea={idea} index={i} />
          ))}
        </div>
      )}
    </section>
  );
}
