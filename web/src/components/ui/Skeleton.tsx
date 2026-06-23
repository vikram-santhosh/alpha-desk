import { cn } from "@/lib/cn";

interface SkeletonProps {
  className?: string;
  circle?: boolean;
}

export function Skeleton({ className, circle = false }: SkeletonProps) {
  return (
    <div
      className={cn(
        "relative overflow-hidden bg-(--color-surface-elevated)",
        "border border-(--color-border-subtle)",
        "before:absolute before:inset-0 before:-translate-x-full",
        "before:bg-[linear-gradient(90deg,transparent_0%,rgba(255,255,255,0.06)_50%,transparent_100%)]",
        "before:animate-[shimmer_1.6s_infinite]",
        circle ? "rounded-full" : "rounded-xl",
        className
      )}
      aria-hidden="true"
    />
  );
}
