import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Tooltip({ content, children, className }: TooltipProps) {
  return (
    <span
      className={cn("group relative inline-flex", className)}
      title={typeof content === "string" ? content : undefined}
    >
      {children}
      <span
        className={cn(
          "pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2",
          "whitespace-nowrap rounded-lg border border-(--color-border-subtle)",
          "bg-(--color-surface-glass-hi) px-2.5 py-1.5 text-xs text-(--color-text-primary)",
          "shadow-[var(--shadow-glass)] backdrop-blur-xl",
          "opacity-0 transition-opacity duration-150 group-hover:opacity-100"
        )}
        role="tooltip"
      >
        {content}
      </span>
    </span>
  );
}
