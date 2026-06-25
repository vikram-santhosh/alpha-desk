import { cn } from "@/lib/cn";
import { Bot } from "lucide-react";

interface AgentTagProps {
  name: string;
  confidence: number;
  className?: string;
}

export function AgentTag({ name, confidence, className }: AgentTagProps) {
  const clamped = Math.min(Math.max(confidence, 0), 100);

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-lg border border-(--color-accent-violet)/20",
        "bg-(--color-accent-violet)/10 px-2.5 py-1.5",
        className
      )}
    >
      <Bot className="h-3.5 w-3.5 text-(--color-accent-violet)" aria-hidden="true" />
      <span className="text-xs font-medium text-(--color-accent-violet)">{name}</span>
      <div className="h-1.5 w-12 overflow-hidden rounded-full bg-(--color-accent-violet)/20">
        <div
          className="h-full rounded-full bg-(--color-accent-violet) transition-all duration-700"
          style={{ width: `${clamped}%` }}
        />
      </div>
      <span className="text-[10px] tabular-nums text-(--color-accent-violet)/80">{clamped}%</span>
    </div>
  );
}
