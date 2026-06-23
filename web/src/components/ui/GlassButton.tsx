import { cn } from "@/lib/cn";
import { Sparkles } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { forwardRef } from "react";

export interface GlassButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "solid" | "ghost" | "icon";
  sparkle?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  children?: ReactNode;
  className?: string;
}

export const GlassButton = forwardRef<HTMLButtonElement, GlassButtonProps>(
  (
    {
      variant = "solid",
      sparkle = false,
      leftIcon,
      rightIcon,
      children,
      className,
      ...props
    },
    ref
  ) => {
    const isIcon = variant === "icon";

    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-200",
          "focus:outline-none focus:ring-2 focus:ring-(--color-border-glow) focus:ring-offset-0",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          variant === "solid" && [
            "bg-(--color-accent-cyan) text-(--color-surface-base)",
            "hover:bg-[oklch(0.78_0.15_200)] hover:shadow-[0_0_20px_var(--color-glow-cyan)]",
            "px-4 py-2.5 text-sm",
          ],
          variant === "ghost" && [
            "border border-(--color-border-subtle)",
            "bg-(--color-surface-glass) backdrop-blur-md text-(--color-text-primary)",
            "hover:bg-(--color-surface-glass-hi) hover:border-(--color-border-strong)",
            "px-4 py-2.5 text-sm",
          ],
          variant === "icon" && [
            "h-9 w-9 rounded-lg",
            "border border-(--color-border-subtle)",
            "bg-(--color-surface-glass) backdrop-blur-md text-(--color-text-secondary)",
            "hover:bg-(--color-surface-glass-hi) hover:text-(--color-text-primary)",
          ],
          className
        )}
        {...props}
      >
        {sparkle && <Sparkles className="h-4 w-4" aria-hidden="true" />}
        {!sparkle && leftIcon && <span className="flex items-center">{leftIcon}</span>}
        {!isIcon && children}
        {rightIcon && <span className="flex items-center">{rightIcon}</span>}
      </button>
    );
  }
);

GlassButton.displayName = "GlassButton";
