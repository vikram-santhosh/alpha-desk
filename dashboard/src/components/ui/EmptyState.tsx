import { cn } from "@/lib/cn";
import type { ReactNode } from "react";
import { GlassButton } from "./GlassButton";

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
}

export function EmptyState({
  title,
  description,
  icon,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center px-6 py-12",
        className
      )}
    >
      {icon && (
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-(--color-border-subtle) bg-(--color-surface-glass) text-(--color-text-secondary)">
          {icon}
        </div>
      )}
      <h3 className="text-base font-semibold text-(--color-text-primary)">{title}</h3>
      {description && (
        <p className="mt-1 max-w-xs text-sm text-(--color-text-secondary)">{description}</p>
      )}
      {action && (
        <GlassButton variant="ghost" onClick={action.onClick} className="mt-5">
          {action.label}
        </GlassButton>
      )}
    </div>
  );
}
