import { cn } from "@/lib/cn";
import { Command, Server, Wifi } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { formatDateTime } from "@/lib/format";
import { GlassButton } from "@/components/ui/GlassButton";
import { AuroraBackground } from "./AuroraBackground";
import { Sidebar } from "./Sidebar";

interface AppShellProps {
  children: ReactNode;
  activeNavId?: string;
  onNavigate?: (id: string) => void;
  onOpenCommandPalette?: () => void;
  dataAsOf?: string;
  connected?: boolean;
}

export function AppShell({
  children,
  activeNavId = "dashboard",
  onNavigate,
  onOpenCommandPalette,
  dataAsOf,
  connected = true,
}: AppShellProps) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <AuroraBackground>
      <div className="flex min-h-screen">
        <Sidebar activeId={activeNavId} onNavigate={onNavigate} />

        <div className="flex flex-1 flex-col lg:ml-0">
          {/* Top bar */}
          <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-(--color-border-subtle) bg-(--color-surface-base)/70 px-4 backdrop-blur-xl sm:px-6">
            <div className="flex items-center gap-3">
              {onOpenCommandPalette ? (
                <>
                  <GlassButton
                    variant="ghost"
                    leftIcon={<Command className="h-4 w-4" />}
                    onClick={onOpenCommandPalette}
                    className="hidden sm:inline-flex"
                  >
                    Ask AlphaDesk…
                  </GlassButton>
                  <GlassButton
                    variant="icon"
                    onClick={onOpenCommandPalette}
                    className="sm:hidden"
                    aria-label="Open command palette"
                  >
                    <Command className="h-4 w-4" />
                  </GlassButton>
                </>
              ) : (
                <div className="hidden items-center gap-2 rounded-xl border border-(--color-border-subtle) bg-(--color-surface-glass) px-3 py-2 text-sm text-(--color-text-secondary) sm:flex">
                  <Server className="h-4 w-4 text-(--color-accent-cyan)" />
                  <span>FastAPI cockpit</span>
                </div>
              )}
            </div>

            <div className="flex items-center gap-4">
              <div className="hidden items-center gap-2 text-xs text-(--color-text-secondary) sm:flex">
                <span className="font-mono">{dataAsOf ? formatDateTime(dataAsOf) : formatDateTime(now.toISOString())}</span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "relative flex h-2 w-2",
                    connected ? "text-(--color-accent-emerald)" : "text-(--color-accent-rose)"
                  )}
                >
                  {connected && (
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75" />
                  )}
                  <span className={cn("relative inline-flex h-2 w-2 rounded-full bg-current", !connected && "animate-pulse")} />
                </span>
                <Wifi
                  className={cn(
                    "h-4 w-4",
                    connected ? "text-(--color-accent-emerald)" : "text-(--color-accent-rose)"
                  )}
                  aria-hidden="true"
                />
              </div>
            </div>
          </header>

          {/* Scrollable content */}
          <main className="flex-1 overflow-y-auto p-4 sm:p-6">{children}</main>
        </div>
      </div>
    </AuroraBackground>
  );
}
