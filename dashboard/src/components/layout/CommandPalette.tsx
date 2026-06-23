import { askAlphaDesk } from "@/lib/api";
import { cn } from "@/lib/cn";
import { scaleIn } from "@/lib/motion";
import type { CommandResult } from "@/types";
import { Command } from "cmdk";
import { motion, AnimatePresence } from "motion/react";
import {
  FileText,
  Globe,
  LayoutDashboard,
  Mail,
  Radio,
  Rocket,
  Search,
  TrendingUp,
  Wallet,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AgentTag } from "@/components/ui/AgentTag";
import { GlassButton } from "@/components/ui/GlassButton";
import { StreamingText } from "@/components/ui/StreamingText";

const commands = [
  { id: "dashboard", label: "Go to Dashboard", icon: LayoutDashboard },
  { id: "portfolio", label: "Go to Portfolio", icon: Wallet },
  { id: "alerts", label: "Go to Alerts", icon: Search },
  { id: "macro", label: "Go to Macro", icon: Globe },
  { id: "sentiment", label: "Go to Sentiment", icon: Radio },
  { id: "research", label: "Go to Research", icon: FileText },
  { id: "moonshots", label: "Go to Moonshots", icon: Rocket },
  { id: "markets", label: "Go to Markets", icon: TrendingUp },
  { id: "digest", label: "Go to Digest", icon: Mail },
];

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onNavigate?: (id: string) => void;
}

export function CommandPalette({ open, onClose, onNavigate }: CommandPaletteProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (open) onClose();
      }
      if (e.key === "Escape" && open) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <CommandPaletteDialog
          key={open ? 1 : 0}
          onClose={onClose}
          onNavigate={onNavigate}
        />
      )}
    </AnimatePresence>
  );
}

interface CommandPaletteDialogProps {
  onClose: () => void;
  onNavigate?: (id: string) => void;
}

function CommandPaletteDialog({ onClose, onNavigate }: CommandPaletteDialogProps) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CommandResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const id = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(id);
  }, []);

  const handleSelect = (value: string) => {
    const nav = commands.find((c) => c.id === value);
    if (nav) {
      onNavigate?.(nav.id);
      onClose();
      return;
    }

    if (value === "ask" && query.trim()) {
      void runQuery(query.trim());
    }
  };

  const runQuery = async (question: string) => {
    setLoading(true);
    try {
      const res = await askAlphaDesk(question);
      setResult(res);
    } finally {
      setLoading(false);
    }
  };

  const isAskQuery =
    query.trim().length > 0 &&
    !commands.some((c) => c.label.toLowerCase().includes(query.toLowerCase()));

  return (
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <motion.div
        variants={scaleIn}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed inset-0 z-[70] flex items-start justify-center p-4 pt-[15vh]"
      >
        <Command
          className={cn(
            "w-full max-w-2xl overflow-hidden rounded-2xl border border-(--color-border-subtle)",
            "bg-(--color-surface-glass-hi) shadow-2xl backdrop-blur-2xl"
          )}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              onClose();
            }
          }}
          shouldFilter
        >
          <div className="flex items-center gap-3 border-b border-(--color-border-subtle) px-4 py-3">
            <Search className="h-5 w-5 text-(--color-text-tertiary)" />
            <Command.Input
              ref={inputRef}
              value={query}
              onValueChange={setQuery}
              placeholder="Ask AlphaDesk anything…"
              className={cn(
                "flex-1 bg-transparent text-base text-(--color-text-primary) placeholder:text-(--color-text-tertiary)",
                "focus:outline-none"
              )}
            />
            <GlassButton variant="icon" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </GlassButton>
          </div>

          <Command.List className="max-h-[60vh] overflow-y-auto p-2">
            {!result && !loading && (
              <>
                <Command.Group
                  heading="Navigation"
                  className="px-2 pb-2 text-xs font-medium uppercase tracking-wider text-(--color-text-tertiary)"
                >
                  {commands.map((cmd) => {
                    const Icon = cmd.icon;
                    return (
                      <Command.Item
                        key={cmd.id}
                        value={cmd.id}
                        onSelect={handleSelect}
                        className={cn(
                          "flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-(--color-text-primary)",
                          "data-[selected=true]:bg-(--color-surface-glass) data-[selected=true]:text-(--color-accent-cyan)"
                        )}
                      >
                        <Icon className="h-4 w-4 text-(--color-text-secondary)" />
                        {cmd.label}
                      </Command.Item>
                    );
                  })}
                </Command.Group>

                {isAskQuery && (
                  <Command.Item
                    value="ask"
                    onSelect={handleSelect}
                    className={cn(
                      "mt-2 flex cursor-pointer items-center gap-3 rounded-xl border border-(--color-border-subtle)",
                      "bg-(--color-surface-glass) px-3 py-3 text-sm text-(--color-text-primary)",
                      "data-[selected=true]:border-(--color-border-glow) data-[selected=true]:text-(--color-accent-cyan)"
                    )}
                  >
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-(--color-accent-violet)/20 text-(--color-accent-violet)">
                      AI
                    </span>
                    Ask AlphaDesk: “{query.trim()}”
                  </Command.Item>
                )}
              </>
            )}

            {loading && (
              <div className="space-y-3 p-4">
                <div className="h-4 w-3/4 animate-pulse rounded bg-(--color-surface-elevated)" />
                <div className="h-4 w-1/2 animate-pulse rounded bg-(--color-surface-elevated)" />
                <div className="h-4 w-2/3 animate-pulse rounded bg-(--color-surface-elevated)" />
              </div>
            )}

            {result && (
              <div className="p-4">
                <div className="mb-3 flex items-center justify-between">
                  <AgentTag name={result.agent} confidence={result.confidence} />
                  <GlassButton variant="ghost" onClick={() => setResult(null)}>
                    Back
                  </GlassButton>
                </div>
                <StreamingText text={result.answer} speed={24} showScanline />
              </div>
            )}

            <Command.Empty className="py-8 text-center text-sm text-(--color-text-secondary)">
              No commands found.
            </Command.Empty>
          </Command.List>
        </Command>
      </motion.div>
    </>
  );
}
