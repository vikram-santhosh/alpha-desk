import { cn } from "@/lib/cn";
import { motion } from "motion/react";
import { useEffect, useState } from "react";

interface GaugeProps {
  value: number;
  min?: number;
  max?: number;
  size?: number;
  strokeWidth?: number;
  label?: string;
  className?: string;
}

export function Gauge({
  value,
  min = 0,
  max = 100,
  size = 120,
  strokeWidth = 10,
  label,
  className,
}: GaugeProps) {
  const clamped = Math.min(Math.max(value, min), max);
  const normalized = (clamped - min) / (max - min);
  const radius = (size - strokeWidth) / 2;
  const circumference = Math.PI * radius;
  const [animatedValue, setAnimatedValue] = useState(min);

  useEffect(() => {
    const timer = setTimeout(() => setAnimatedValue(clamped), 100);
    return () => clearTimeout(timer);
  }, [clamped]);

  const dashOffset = circumference * (1 - (animatedValue - min) / (max - min));

  const rotation = -180;
  const center = size / 2;
  const needleAngle = rotation + normalized * 180;

  return (
    <div
      className={cn("relative inline-flex flex-col items-center", className)}
      style={{ width: size, height: size * 0.65 }}
    >
      <svg
        width={size}
        height={size / 2 + strokeWidth}
        viewBox={`0 0 ${size} ${size / 2 + strokeWidth}`}
        className="overflow-visible"
      >
        <defs>
          <linearGradient id="gauge-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="var(--color-accent-rose)" />
            <stop offset="50%" stopColor="var(--color-accent-amber)" />
            <stop offset="100%" stopColor="var(--color-accent-emerald)" />
          </linearGradient>
        </defs>

        {/* Background arc */}
        <path
          d={`M ${strokeWidth / 2} ${size / 2} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2} ${size / 2}`}
          fill="none"
          stroke="var(--color-surface-elevated)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />

        {/* Value arc */}
        <motion.path
          d={`M ${strokeWidth / 2} ${size / 2} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2} ${size / 2}`}
          fill="none"
          stroke="url(#gauge-gradient)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: dashOffset }}
          transition={{ duration: 1, ease: [0.25, 0.46, 0.45, 0.94] }}
        />

        {/* Needle */}
        <motion.g
          initial={{ rotate: -180 }}
          animate={{ rotate: needleAngle }}
          transition={{ duration: 1, ease: [0.25, 0.46, 0.45, 0.94] }}
          style={{ transformOrigin: `${center}px ${size / 2}px` }}
        >
          <line
            x1={center}
            y1={size / 2}
            x2={center}
            y2={strokeWidth + 4}
            stroke="var(--color-text-primary)"
            strokeWidth={2.5}
            strokeLinecap="round"
          />
        </motion.g>

        {/* Pivot */}
        <circle
          cx={center}
          cy={size / 2}
          r={5}
          fill="var(--color-surface-glass-hi)"
          stroke="var(--color-text-primary)"
          strokeWidth={2}
        />
      </svg>

      {label && (
        <span className="absolute bottom-0 text-[10px] font-medium uppercase tracking-wider text-(--color-text-secondary)">
          {label}
        </span>
      )}
    </div>
  );
}
