import { useEffect, useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Activity, RefreshCw } from "lucide-react";
import { fetchMacroRegime, fetchMacroThemes } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlassButton } from "@/components/ui/GlassButton";
import { MacroRegimeSection } from "./MacroRegimeSection";
import { MacroThemeCard } from "./MacroThemeCard";
import { MacroSignalFeed } from "./MacroSignalFeed";
import { signalsFromThemes, type MacroSignal } from "./utils";
import { stagger, rise } from "@/lib/motion";
import type { MacroRegime, MacroTheme } from "@/types";

export default function MacroView() {
  const reduceMotion = useReducedMotion();
  const [regime, setRegime] = useState<MacroRegime | null>(null);
  const [themes, setThemes] = useState<MacroTheme[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [regimeData, themesData] = await Promise.all([fetchMacroRegime(), fetchMacroThemes()]);
      setRegime(regimeData);
      setThemes(themesData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load macro data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const signals: MacroSignal[] = useMemo(() => signalsFromThemes(themes), [themes]);

  if (error) {
    return (
      <div className="mx-auto max-w-7xl">
        <GlassCard className="p-8">
          <EmptyState
            title="Macro scanner offline"
            description={error}
            icon={<Activity className="h-5 w-5" />}
            action={{ label: "Retry", onClick: load }}
          />
        </GlassCard>
      </div>
    );
  }

  return (
    <motion.div
      className="mx-auto max-w-7xl"
      variants={stagger}
      initial={reduceMotion ? "visible" : "hidden"}
      animate="visible"
    >
      <motion.div
        variants={rise}
        className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"
      >
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-(--color-text-primary)">Macro Regime</h1>
          <p className="text-sm text-(--color-text-secondary)">
            AI-scanned macro themes and regime gauge.
          </p>
        </div>
        <GlassButton
          variant="ghost"
          onClick={load}
          disabled={loading}
          className="self-start"
          leftIcon={<RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />}
        >
          Refresh
        </GlassButton>
      </motion.div>

      <div className="space-y-6">
        <MacroRegimeSection regime={regime} loading={loading} />

        <div>
          <motion.h2
            variants={rise}
            className="mb-4 text-lg font-semibold text-(--color-text-primary)"
          >
            Active Themes
          </motion.h2>

          {loading && themes.length === 0 ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-64 w-full" />
              ))}
            </div>
          ) : themes.length === 0 ? (
            <GlassCard className="p-6">
              <EmptyState
                title="No macro themes"
                description="Macro scanner hasn’t identified any active themes yet."
                icon={<Activity className="h-5 w-5" />}
              />
            </GlassCard>
          ) : (
            <motion.div
              className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3"
              variants={stagger}
              initial={reduceMotion ? "visible" : "hidden"}
              animate="visible"
            >
              {themes.map((theme) => (
                <MacroThemeCard key={theme.id} theme={theme} />
              ))}
            </motion.div>
          )}
        </div>

        <motion.div variants={rise}>
          <MacroSignalFeed signals={signals} />
        </motion.div>
      </div>
    </motion.div>
  );
}
