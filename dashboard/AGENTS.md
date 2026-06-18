# AGENTS.md — AlphaDesk Dashboard

## Scope
- This directory is a React + Vite + TS frontend. NEVER modify ../  (the Python backend).
- All data flows through `src/lib/api.ts`. Today it returns mock data; keep the function
  signatures stable so a real backend can swap in later.

## Setup
- `npm install` once. Node 22+.
- Dev: `npm run dev`. Build: `npm run build`. Typecheck: `npm run typecheck` (alias for `tsc --noEmit`).

## Definition of done (run these yourself, fix failures, do not ask me to)
- `npm run typecheck` → zero errors
- `npm run build` → zero errors, zero warnings
- `npm run lint` → clean
- Every route renders with no console errors (verify by reading each view's JSX + imports).

## Conventions
- Components: PascalCase files. Hooks: `useX`. One component per file.
- Styling: Tailwind v4 utility classes + the design tokens in `src/index.css`. No inline hex colors.
- Animation: `motion/react` (NOT framer-motion). Perf-critical loops use CSS @keyframes, not JS.
- Currency/numbers: format via `src/lib/format.ts` (Intl.NumberFormat). Always tabular-nums in tables.
- Accessibility: text contrast ≥ 4.5:1 on the dark surface; respect `prefers-reduced-motion`.
