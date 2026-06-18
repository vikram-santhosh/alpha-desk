import { cn } from "@/lib/cn";
import { motion } from "motion/react";
import {
  BellRing,
  FlaskConical,
  Globe,
  LayoutDashboard,
  Mail,
  Menu,
  Radio,
  Rocket,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { useState } from "react";
import { GlassButton } from "@/components/ui/GlassButton";

export type NavItem = {
  id: string;
  label: string;
  icon: React.ElementType;
};

const navItems: NavItem[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "portfolio", label: "Portfolio", icon: Wallet },
  { id: "alerts", label: "Alerts", icon: BellRing },
  { id: "macro", label: "Macro", icon: Globe },
  { id: "sentiment", label: "Sentiment", icon: Radio },
  { id: "research", label: "Research", icon: FlaskConical },
  { id: "moonshots", label: "Moonshots", icon: Rocket },
  { id: "markets", label: "Markets", icon: TrendingUp },
  { id: "digest", label: "Digest", icon: Mail },
];

interface SidebarProps {
  activeId?: string;
  onNavigate?: (id: string) => void;
  collapsed?: boolean;
  lastSync?: string;
}

export function Sidebar({
  activeId = "dashboard",
  onNavigate,
  collapsed = false,
  lastSync = "Just now",
}: SidebarProps) {
  const [mobileOpen, setMobileOpen] = useState(false);

  const renderNav = (isMobile = false) => (
    <nav className="flex flex-1 flex-col gap-1 px-3 py-4">
      {navItems.map((item) => {
        const Icon = item.icon;
        const active = item.id === activeId;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => {
              onNavigate?.(item.id);
              if (isMobile) setMobileOpen(false);
            }}
            className={cn(
              "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
              active
                ? "text-(--color-accent-cyan)"
                : "text-(--color-text-secondary) hover:bg-(--color-surface-glass) hover:text-(--color-text-primary)"
            )}
          >
            {active && !collapsed && (
              <motion.div
                layoutId="sidebar-active"
                className="absolute inset-0 -z-10 rounded-xl border border-(--color-border-subtle) bg-(--color-surface-glass)"
                transition={{ type: "spring", stiffness: 400, damping: 32 }}
              />
            )}
            {!collapsed && active && (
              <motion.div
                layoutId="sidebar-accent"
                className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-(--color-accent-cyan)"
                transition={{ type: "spring", stiffness: 400, damping: 32 }}
              />
            )}
            <Icon className="h-[18px] w-[18px] shrink-0" />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </button>
        );
      })}
    </nav>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <div className="fixed left-4 top-4 z-40 lg:hidden">
        <GlassButton variant="icon" onClick={() => setMobileOpen(true)} aria-label="Open menu">
          <Menu className="h-5 w-5" />
        </GlassButton>
      </div>

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "hidden lg:flex h-screen flex-col border-r border-(--color-border-subtle)",
          "bg-(--color-surface-base)/80 backdrop-blur-xl transition-[width] duration-300",
          collapsed ? "w-[68px]" : "w-[248px]"
        )}
      >
        <div className="flex h-16 items-center gap-2.5 px-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-(--color-accent-cyan) text-(--color-surface-base)">
            <span className="text-sm font-bold">α</span>
          </div>
          {!collapsed && (
            <span className="text-base font-semibold tracking-tight text-(--color-text-primary)">
              AlphaDesk
            </span>
          )}
        </div>

        {renderNav()}

        <div className="border-t border-(--color-border-subtle) p-3">
          <div
            className={cn(
              "flex items-center gap-2 rounded-xl border border-(--color-border-subtle) bg-(--color-surface-glass) px-3 py-2",
              collapsed && "justify-center px-2"
            )}
          >
            <kbd className="hidden rounded-md bg-(--color-surface-elevated) px-1.5 py-0.5 text-[10px] font-mono text-(--color-text-secondary) lg:inline-block">
              ⌘K
            </kbd>
            {!collapsed && (
              <span className="text-xs text-(--color-text-tertiary)">Command</span>
            )}
          </div>
          <div
            className={cn(
              "mt-3 flex items-center gap-2 text-xs text-(--color-text-tertiary)",
              collapsed && "justify-center"
            )}
          >
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-(--color-accent-emerald) opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-(--color-accent-emerald)" />
            </span>
            {!collapsed && <span>Synced {lastSync}</span>}
          </div>
        </div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
            onClick={() => setMobileOpen(false)}
          />
          <motion.div
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            className="fixed left-0 top-0 z-50 h-full w-[260px] border-r border-(--color-border-subtle) bg-(--color-surface-base)/95 backdrop-blur-2xl lg:hidden"
          >
              <div className="flex h-16 items-center gap-2.5 px-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-(--color-accent-cyan) text-(--color-surface-base)">
                  <span className="text-sm font-bold">α</span>
                </div>
                <span className="text-base font-semibold tracking-tight text-(--color-text-primary)">
                  AlphaDesk
                </span>
              </div>
              {renderNav(true)}
          </motion.div>
        </>
      )}
    </>
  );
}
