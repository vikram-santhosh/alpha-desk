import { cn } from "@/lib/cn";
import { motion } from "motion/react";
import type { ElementType, ReactNode } from "react";

export type GlowColor = "cyan" | "emerald" | "rose" | "violet" | "amber";

interface GlassCardProps<T extends ElementType = "div"> {
  as?: T;
  glow?: GlowColor | false;
  hoverLift?: boolean;
  className?: string;
  children: ReactNode;
}

const glowMap: Record<GlowColor, string> = {
  cyan: "shadow-[0_0_28px_0_var(--color-glow-cyan)]",
  emerald: "shadow-[0_0_28px_0_var(--color-glow-emerald)]",
  rose: "shadow-[0_0_28px_0_var(--color-glow-rose)]",
  violet: "shadow-[0_0_28px_0_var(--color-glow-violet)]",
  amber: "shadow-[0_0_28px_0_var(--color-glow-amber)]",
};

export function GlassCard<T extends ElementType = "div">({
  as,
  glow = false,
  hoverLift = true,
  className,
  children,
  ...rest
}: GlassCardProps<T> & Omit<React.ComponentPropsWithoutRef<T>, keyof GlassCardProps<T>>) {
  const Component = as ?? motion.div;

  return (
    <Component
      className={cn(
        "relative overflow-hidden rounded-[var(--radius-card)]",
        "border border-(--color-border-subtle)",
        "bg-(--color-surface-glass) backdrop-blur-xl",
        "shadow-[var(--shadow-glass)]",
        "before:pointer-events-none before:absolute before:inset-0 before:rounded-[inherit]",
        "before:bg-[linear-gradient(135deg,rgba(255,255,255,0.06)_0%,transparent_50%,rgba(255,255,255,0.02)_100%)]",
        "after:pointer-events-none after:absolute after:inset-0 after:rounded-[inherit] after:opacity-[0.04]",
        "after:bg-[repeating-radial-gradient(circle_at_50%_50%,rgba(255,255,255,0.08)_0px,rgba(255,255,255,0.08)_1px,transparent_1px,transparent_4px)]",
        hoverLift && "transition-transform duration-300 ease-out hover:-translate-y-0.5",
        glow && glowMap[glow],
        className
      )}
      {...(rest as React.ComponentPropsWithoutRef<T>)}
    >
      <div className="relative z-10">{children}</div>
    </Component>
  );
}
