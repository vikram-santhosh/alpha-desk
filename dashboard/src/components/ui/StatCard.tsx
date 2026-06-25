import { cn } from "@/lib/cn";
import { motion, useMotionValue, useTransform, animate } from "motion/react";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { DeltaChip } from "./DeltaChip";

interface StatCardProps {
  label: string;
  value: number;
  prefix?: string;
  suffix?: string;
  delta?: number;
  formatter?: (value: number) => string;
  sparkline?: ReactNode;
  className?: string;
}

export function StatCard({
  label,
  value,
  prefix = "",
  suffix = "",
  delta,
  formatter = (v) => v.toLocaleString("en-US", { maximumFractionDigits: 2 }),
  sparkline,
  className,
}: StatCardProps) {
  const count = useMotionValue(0);
  const rounded = useTransform(count, (v) => formatter(v));
  const [display, setDisplay] = useState(formatter(0));
  const ref = useRef<HTMLDivElement>(null);
  const [hasAnimated, setHasAnimated] = useState(false);

  useEffect(() => {
    const unsub = rounded.on("change", (v) => setDisplay(String(v)));
    return () => unsub();
  }, [rounded]);

  useEffect(() => {
    if (hasAnimated) return;
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setHasAnimated(true);
          animate(count, value, {
            duration: 1.2,
            ease: [0.25, 0.46, 0.45, 0.94],
          });
          observer.disconnect();
        }
      },
      { threshold: 0.2 }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [count, value, hasAnimated]);

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
      className={cn(
        "relative overflow-hidden rounded-[var(--radius-card)]",
        "border border-(--color-border-subtle)",
        "bg-(--color-surface-glass) backdrop-blur-xl",
        "p-4 shadow-[var(--shadow-glass)]",
        className
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-(--color-text-secondary) uppercase tracking-wide">
            {label}
          </p>
          <div className="mt-1.5 flex items-baseline gap-1">
            <span className="text-(--color-text-tertiary) text-sm">{prefix}</span>
            <span className="text-3xl font-semibold tracking-tight text-(--color-text-primary) font-mono tabular-nums">
              {display}
            </span>
            <span className="text-(--color-text-tertiary) text-sm">{suffix}</span>
          </div>
          {typeof delta === "number" && (
            <div className="mt-2">
              <DeltaChip value={delta} />
            </div>
          )}
        </div>
        {sparkline && <div className="shrink-0">{sparkline}</div>}
      </div>
    </motion.div>
  );
}
