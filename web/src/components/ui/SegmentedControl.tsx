import { cn } from "@/lib/cn";
import { motion } from "motion/react";

interface Option<T extends string = string> {
  value: T;
  label: string;
}

interface SegmentedControlProps<T extends string = string> {
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  layoutId?: string;
  className?: string;
}

export function SegmentedControl<T extends string = string>({
  options,
  value,
  onChange,
  layoutId = "segment-indicator",
  className,
}: SegmentedControlProps<T>) {
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-xl border border-(--color-border-subtle)",
        "bg-(--color-surface-elevated)/60 p-1 backdrop-blur-md",
        className
      )}
      role="tablist"
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "relative z-10 px-3 py-1.5 text-xs font-medium transition-colors",
              active ? "text-(--color-text-primary)" : "text-(--color-text-secondary) hover:text-(--color-text-primary)"
            )}
          >
            {active && (
              <motion.div
                layoutId={layoutId}
                className="absolute inset-0 -z-10 rounded-lg bg-(--color-surface-glass-hi) border border-(--color-border-subtle) shadow-sm"
                transition={{ type: "spring", stiffness: 400, damping: 30 }}
              />
            )}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
