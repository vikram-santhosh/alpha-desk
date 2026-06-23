import { cn } from "@/lib/cn";
import { useEffect, useState } from "react";

interface StreamingTextProps {
  text: string;
  speed?: number;
  onComplete?: () => void;
  showScanline?: boolean;
  className?: string;
}

export function StreamingText(props: StreamingTextProps) {
  // Remount when the text changes so the reveal animation restarts cleanly.
  return <StreamingTextInner key={props.text} {...props} />;
}

function StreamingTextInner({
  text,
  speed = 18,
  onComplete,
  showScanline = false,
  className,
}: StreamingTextProps) {
  const [revealed, setRevealed] = useState(0);
  const completed = revealed >= text.length;

  useEffect(() => {
    if (completed) {
      onComplete?.();
      return;
    }

    const timeout = setTimeout(() => {
      setRevealed((prev) => Math.min(prev + 1, text.length));
    }, 1000 / speed);

    return () => clearTimeout(timeout);
  }, [revealed, text, speed, onComplete, completed]);

  return (
    <div className={cn("relative", className)}>
      {showScanline && !completed && (
        <div className="mb-3 h-1 w-full overflow-hidden rounded-full bg-(--color-surface-elevated)">
          <div
            className="h-full w-1/3 rounded-full bg-gradient-to-r from-transparent via-(--color-accent-cyan) to-transparent opacity-70"
            style={{ animation: "scanline 1.2s linear infinite" }}
          />
        </div>
      )}
      <span className="whitespace-pre-wrap text-sm leading-relaxed text-(--color-text-primary)">
        {text.slice(0, revealed)}
        {!completed && (
          <span
            className="ml-0.5 inline-block h-4 w-0.5 bg-(--color-accent-cyan) align-middle"
            style={{ animation: "caret-blink 1s step-end infinite" }}
          />
        )}
      </span>
    </div>
  );
}
