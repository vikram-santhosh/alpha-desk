import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";

interface DeltaChipProps {
  value: number;
  className?: string;
}

export function DeltaChip({ value, className }: DeltaChipProps) {
  const positive = value >= 0;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium tabular-nums",
        positive ? "text-(--color-accent-emerald)" : "text-(--color-accent-rose)",
        className
      )}
    >
      <svg
        width="8"
        height="8"
        viewBox="0 0 8 8"
        fill="currentColor"
        className={cn("transition-transform", !positive && "rotate-180")}
        aria-hidden="true"
      >
        <path d="M4 1L7.5 7H0.5L4 1Z" />
      </svg>
      {formatPercent(value)}
    </span>
  );
}
