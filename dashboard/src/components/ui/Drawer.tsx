import { cn } from "@/lib/cn";
import { slideInRight } from "@/lib/motion";
import { motion, AnimatePresence } from "motion/react";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { GlassButton } from "./GlassButton";

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Drawer({ open, onClose, title, children, className }: DrawerProps) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.div
            variants={slideInRight}
            initial="hidden"
            animate="visible"
            exit="exit"
            className={cn(
              "fixed right-0 top-0 z-50 h-full w-full max-w-md",
              "border-l border-(--color-border-subtle)",
              "bg-(--color-surface-glass) backdrop-blur-2xl",
              "shadow-[-8px_0_32px_rgba(0,0,0,0.4)]",
              "flex flex-col",
              className
            )}
            role="dialog"
            aria-modal="true"
          >
            <div className="flex items-center justify-between border-b border-(--color-border-subtle) px-5 py-4">
              {title ? (
                <h2 className="text-base font-semibold text-(--color-text-primary)">{title}</h2>
              ) : (
                <span />
              )}
              <GlassButton variant="icon" onClick={onClose} aria-label="Close drawer">
                <X className="h-4 w-4" />
              </GlassButton>
            </div>
            <div className="flex-1 overflow-y-auto p-5">{children}</div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
