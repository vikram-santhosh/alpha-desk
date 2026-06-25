import type { MacroTheme } from "@/types";

export interface MacroSignal {
  id: string;
  themeId: string;
  themeTitle: string;
  source: string;
  text: string;
  impact: "positive" | "neutral" | "negative";
  scannedAt: string;
}

export function minutesAgo(iso: string): string {
  const diff = Math.max(0, Date.now() - new Date(iso).getTime());
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins === 1) return "1 min ago";
  return `${mins} mins ago`;
}

export function signalsFromThemes(themes: MacroTheme[]): MacroSignal[] {
  return themes
    .flatMap((theme) =>
      theme.bullets.map((bullet, idx) => ({
        id: `${theme.id}-${idx}`,
        themeId: theme.id,
        themeTitle: theme.title,
        source: theme.agent,
        text: bullet,
        impact:
          theme.status === "risk_on"
            ? ("positive" as const)
            : theme.status === "risk_off"
              ? ("negative" as const)
              : ("neutral" as const),
        scannedAt: theme.scannedAt,
      })),
    )
    .sort((a, b) => new Date(b.scannedAt).getTime() - new Date(a.scannedAt).getTime());
}
