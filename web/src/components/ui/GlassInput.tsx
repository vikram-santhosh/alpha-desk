import { cn } from "@/lib/cn";
import type { InputHTMLAttributes } from "react";
import { forwardRef } from "react";

export interface GlassInputProps extends InputHTMLAttributes<HTMLInputElement> {
  className?: string;
}

export const GlassInput = forwardRef<HTMLInputElement, GlassInputProps>(
  ({ className, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          "w-full rounded-xl border border-(--color-border-subtle)",
          "bg-(--color-surface-glass) backdrop-blur-md",
          "px-3.5 py-2.5 text-sm text-(--color-text-primary)",
          "placeholder:text-(--color-text-tertiary)",
          "shadow-[var(--shadow-glass)]",
          "focus:outline-none focus:border-(--color-border-glow) focus:ring-1 focus:ring-(--color-border-glow)",
          "transition-all duration-200",
          className
        )}
        {...props}
      />
    );
  }
);

GlassInput.displayName = "GlassInput";
