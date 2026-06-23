import type { SparklinePoint } from "@/types";
import { cn } from "@/lib/cn";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
} from "recharts";

interface SparklineProps {
  data: SparklinePoint[];
  color?: "emerald" | "rose" | "cyan" | "violet" | "amber";
  height?: number;
  className?: string;
}

const colorMap: Record<NonNullable<SparklineProps["color"]>, string> = {
  emerald: "var(--color-accent-emerald)",
  rose: "var(--color-accent-rose)",
  cyan: "var(--color-accent-cyan)",
  violet: "var(--color-accent-violet)",
  amber: "var(--color-accent-amber)",
};

export function Sparkline({
  data,
  color = "emerald",
  height = 40,
  className,
}: SparklineProps) {
  const stroke = colorMap[color];

  return (
    <div className={cn("w-full", className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
          <defs>
            <linearGradient id={`spark-${color}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.35} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="value"
            stroke={stroke}
            strokeWidth={2}
            fill={`url(#spark-${color})`}
            isAnimationActive={false}
            dot={false}
            activeDot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
