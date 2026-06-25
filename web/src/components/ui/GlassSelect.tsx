import { cn } from "@/lib/cn";
import { ChevronDown } from "lucide-react";
import type { SelectHTMLAttributes, ReactNode } from "react";
import { forwardRef } from "react";

export interface GlassSelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  className?: string;
  label?: ReactNode;
}

export const GlassSelect = forwardRef<HTMLSelectElement, GlassSelectProps>(
  ({ className, children, label, ...props }, ref) => {
    return (
      <div className={cn("relative", className)}>
        {label && (
          <label className="mb-1.5 block text-xs font-medium text-(--color-text-secondary)">
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            className={cn(
              "w-full appearance-none rounded-xl border border-(--color-border-subtle)",
              "bg-(--color-surface-glass) backdrop-blur-md",
              "px-3.5 py-2.5 pr-9 text-sm text-(--color-text-primary)",
              "shadow-[var(--shadow-glass)]",
              "focus:outline-none focus:border-(--color-border-glow) focus:ring-1 focus:ring-(--color-border-glow)",
              "transition-all duration-200"
            )}
            {...props}
          >
            {children}
          </select>
          <ChevronDown
            className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-(--color-text-tertiary)"
            aria-hidden="true"
          />
        </div>
      </div>
    );
  }
);

GlassSelect.displayName = "GlassSelect";
