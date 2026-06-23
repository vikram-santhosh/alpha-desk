import { cn } from "@/lib/cn";
import { motion } from "motion/react";
import type { ReactNode } from "react";

export type StatusVariant = "info" | "success" | "warning" | "critical" | "neutral";

interface StatusBadgeProps {
  variant?: StatusVariant;
  pulse?: boolean;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}

const variantStyles: Record<StatusVariant, string> = {
  info: "bg-(--color-accent-cyan)/10 text-(--color-accent-cyan) border-(--color-accent-cyan)/20",
  success: "bg-(--color-accent-emerald)/10 text-(--color-accent-emerald) border-(--color-accent-emerald)/20",
  warning: "bg-(--color-accent-amber)/10 text-(--color-accent-amber) border-(--color-accent-amber)/20",
  critical: "bg-(--color-accent-rose)/10 text-(--color-accent-rose) border-(--color-accent-rose)/20",
  neutral: "bg-(--color-surface-elevated)/60 text-(--color-text-secondary) border-(--color-border-subtle)",
};

export function StatusBadge({
  variant = "neutral",
  pulse = false,
  icon,
  children,
  className,
}: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[var(--radius-pill)] text-xs font-medium border",
        variantStyles[variant],
        className
      )}
    >
      {pulse && variant === "critical" && (
        <motion.span
          className="relative flex h-1.5 w-1.5"
          aria-hidden="true"
        >
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-(--color-accent-rose) opacity-75" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-(--color-accent-rose)" />
        </motion.span>
      )}
      {!pulse && icon && <span className="flex items-center justify-center">{icon}</span>}
      {pulse && !icon && (
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />
      )}
      {children}
    </span>
  );
}
