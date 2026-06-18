import type { Moonshot } from "@/types";
import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { fetchMoonshots } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlassButton } from "@/components/ui/GlassButton";
import { Rocket, RefreshCw, Orbit } from "lucide-react";
import { MoonshotCard } from "./MoonshotCard";
import { useReducedMotion } from "@/lib/useReducedMotion";

const ALL_SECTORS = "All";

export default function MoonshotsView() {
  const [moonshots, setMoonshots] = useState<Moonshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSector, setSelectedSector] = useState<string>(ALL_SECTORS);
  const reducedMotion = useReducedMotion();

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMoonshots();
      setMoonshots(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load moonshots");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const sectors = useMemo(
    () => Array.from(new Set(moonshots.map((m) => m.sector))).sort(),
    [moonshots]
  );

  const filtered = useMemo(() => {
    if (selectedSector === ALL_SECTORS) return moonshots;
    return moonshots.filter((m) => m.sector === selectedSector);
  }, [moonshots, selectedSector]);

  return (
    <section className="mx-auto max-w-6xl px-4 py-6 md:py-8">
      <motion.header
        className="mb-6 flex flex-col gap-4 md:flex-row md:items-center md:justify-between"
        initial={reducedMotion ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.25, 0.46, 0.45, 0.94] }}
      >
        <div>
          <div className="flex items-center gap-2">
            <Rocket className="h-5 w-5 text-(--color-accent-violet)" aria-hidden="true" />
            <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">
              Moonshots
            </h1>
          </div>
          <p className="mt-1 text-sm text-(--color-text-secondary)">
            High-risk / high-reward ideas outside the core portfolio.
          </p>
        </div>
        <GlassButton
          variant="ghost"
          leftIcon={<RefreshCw className="h-4 w-4" />}
          onClick={load}
          disabled={loading}
        >
          Refresh
        </GlassButton>
      </motion.header>

      {loading ? (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Skeleton className="h-9 w-16" />
            <Skeleton className="h-9 w-20" />
            <Skeleton className="h-9 w-24" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Skeleton className="h-80" />
            <Skeleton className="h-80" />
            <Skeleton className="h-80" />
            <Skeleton className="h-80" />
          </div>
        </div>
      ) : error ? (
        <GlassCard glow="rose" className="p-6">
          <EmptyState
            title="Could not load moonshots"
            description={error}
            icon={<Orbit className="h-6 w-6" />}
            action={{ label: "Try again", onClick: load }}
          />
        </GlassCard>
      ) : (
        <>
          <motion.div
            className="mb-6 flex flex-wrap gap-2"
            initial={reducedMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.35,
              delay: reducedMotion ? 0 : 0.1,
              ease: [0.25, 0.46, 0.45, 0.94],
            }}
          >
            <button
              type="button"
              onClick={() => setSelectedSector(ALL_SECTORS)}
              className={`rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${
                selectedSector === ALL_SECTORS
                  ? "border-(--color-accent-violet)/30 bg-(--color-accent-violet)/15 text-(--color-accent-violet)"
                  : "border-(--color-border-subtle) bg-(--color-surface-glass) text-(--color-text-secondary) hover:border-(--color-border-strong) hover:text-(--color-text-primary)"
              }`}
            >
              {ALL_SECTORS}
            </button>
            {sectors.map((sector) => {
              const active = selectedSector === sector;
              return (
                <button
                  key={sector}
                  type="button"
                  onClick={() => setSelectedSector(sector)}
                  className={`rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${
                    active
                      ? "border-(--color-accent-violet)/30 bg-(--color-accent-violet)/15 text-(--color-accent-violet)"
                      : "border-(--color-border-subtle) bg-(--color-surface-glass) text-(--color-text-secondary) hover:border-(--color-border-strong) hover:text-(--color-text-primary)"
                  }`}
                >
                  {sector}
                </button>
              );
            })}
          </motion.div>

          {filtered.length === 0 ? (
            <GlassCard className="p-6">
              <EmptyState
                title="No moonshots match this filter"
                description="Try selecting a different sector or refresh the list."
                icon={<Rocket className="h-6 w-6" />}
                action={{ label: "Clear filter", onClick: () => setSelectedSector(ALL_SECTORS) }}
              />
            </GlassCard>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((moonshot, index) => (
                <MoonshotCard key={moonshot.id} moonshot={moonshot} index={index} />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
