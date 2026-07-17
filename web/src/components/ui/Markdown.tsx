import { isValidElement } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/cn";

// Flatten react children to plain text — used only to spot the lead "BOTTOM LINE"
// paragraph so it can render as a callout.
function textOf(node: ReactNode): string {
  if (node == null || node === false) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
}

// GitHub-flavored markdown mapped onto the cockpit's glass/dark design tokens.
// The deployment report is table- and section-heavy, so tables and section
// rhythm get the most attention.
const components: Components = {
  h1: ({ children }) => (
    <h1 className="mb-2 text-2xl font-bold tracking-tight text-(--color-text-primary)">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-10 mb-4 border-b border-(--color-border-subtle) pb-2 text-xl font-semibold tracking-tight text-(--color-text-primary)">
      {children}
    </h2>
  ),
  // The report's primary sections come in as h3 ("### 1. Macro Backdrop").
  h3: ({ children }) => (
    <h3 className="mt-9 mb-3 flex items-center gap-2.5 text-lg font-semibold tracking-tight text-(--color-text-primary)">
      <span className="h-5 w-1 shrink-0 rounded-full bg-(--color-accent-cyan)" aria-hidden="true" />
      {children}
    </h3>
  ),
  h4: ({ children }) => (
    <h4 className="mt-6 mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-(--color-accent-cyan)">
      {children}
    </h4>
  ),
  p: ({ children }) => {
    if (textOf(children).trimStart().toUpperCase().startsWith("BOTTOM LINE")) {
      return (
        <div className="my-5 rounded-xl border border-(--color-accent-cyan)/30 bg-(--color-accent-cyan)/8 p-4 text-sm leading-7 text-(--color-text-primary)">
          {children}
        </div>
      );
    }
    return <p className="my-4 text-sm leading-7 text-(--color-text-secondary)">{children}</p>;
  },
  ul: ({ children }) => (
    <ul className="my-4 list-disc space-y-1.5 pl-5 text-sm leading-7 text-(--color-text-secondary) marker:text-(--color-accent-cyan)/60">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-4 list-decimal space-y-1.5 pl-5 text-sm leading-7 text-(--color-text-secondary) marker:text-(--color-text-tertiary)">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="pl-1">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-(--color-text-primary)">{children}</strong>,
  em: ({ children }) => <em className="italic text-(--color-text-tertiary)">{children}</em>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="font-medium text-(--color-accent-cyan) underline decoration-(--color-accent-cyan)/40 underline-offset-2 hover:decoration-(--color-accent-cyan)"
    >
      {children}
    </a>
  ),
  hr: () => <hr className="my-8 border-0 border-t border-(--color-border-subtle)" />,
  blockquote: ({ children }) => (
    <blockquote className="my-4 rounded-r-lg border-l-2 border-(--color-accent-cyan) bg-(--color-surface-elevated)/40 py-1.5 pl-4 pr-3 text-sm italic text-(--color-text-secondary)">
      {children}
    </blockquote>
  ),
  code: ({ children }) => (
    <code className="rounded-md bg-(--color-surface-elevated) px-1.5 py-0.5 font-mono text-[0.82em] text-(--color-accent-cyan)">
      {children}
    </code>
  ),
  table: ({ children }) => (
    <div className="my-5 overflow-x-auto rounded-xl border border-(--color-border-subtle) shadow-[var(--shadow-glass)]">
      <table className="w-full border-collapse text-left text-[13px] tabular-nums [&_tbody_tr:nth-child(even)]:bg-(--color-surface-elevated)/25 [&_tbody_tr:hover]:bg-(--color-surface-elevated)/45">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-(--color-surface-elevated)/70">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-(--color-border-subtle) px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-(--color-text-tertiary)">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-(--color-border-subtle)/50 px-4 py-2.5 align-top text-(--color-text-secondary)">
      {children}
    </td>
  ),
};

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("text-(--color-text-secondary)", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
