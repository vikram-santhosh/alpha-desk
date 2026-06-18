# AlphaDesk Dashboard — Handoff Context

## Planned scope
Build a new standalone React frontend for AlphaDesk in `dashboard/`, implementing the **"Aurora Console"** generative-AI design system and 9 investment-research views against mock data shaped like the Python backend's outputs.

Key requirements from the build prompt:
- React + Vite + TypeScript + Tailwind v4 + Motion v12.
- Dark-first glassmorphism UI with oklch tokens, aurora background, grain.
- Reusable UI primitives + layout shell + ⌘K command palette.
- All data flows through a swappable `src/lib/api.ts` seam.
- 9 routes: Command Center, Portfolio, Alerts, Macro, Sentiment, Research, Moonshots, Markets, Digest.
- Quality gate: `npm run typecheck`, `npm run lint`, `npm run build` all clean.

## What was completed

### Foundation
- Scaffolded Vite `react-ts` project in `/Users/vikram/workspace/alpha-desk/dashboard/`.
- Installed all dependencies: `motion`, `react-router-dom`, `lucide-react`, `recharts`, `clsx`, `cmdk`, `tailwindcss`, `@tailwindcss/vite`.
- Wired Tailwind v4 via `@tailwindcss/vite` plugin (no `tailwind.config.js`).
- Wrote `AGENTS.md` with scope, setup, and conventions.

### Design system (`src/index.css`)
- oklch color tokens for surfaces, borders, text, accents (cyan/emerald/amber/rose/violet/blue), glows.
- Geist Sans + Geist Mono font imports.
- Aurora background blobs, grain overlay, custom scrollbar.
- Keyframes: pulse-glow, dot-pulse, shimmer, gradient-shift, scanline, aurora, caret-blink.
- `prefers-reduced-motion` gating.

### Lib / data / types
- `src/types/index.ts` — shared TypeScript types.
- `src/lib/cn.ts` — `clsx` wrapper.
- `src/lib/format.ts` — currency, percent, number, date formatters.
- `src/lib/motion.ts` — shared `motion/react` variants.
- `src/lib/api.ts` — async mock API seam returning promises with small delays.
- `src/lib/useReducedMotion.ts` — single reduced-motion hook.
- `src/data/*.ts` — mock data for portfolio, alerts, macro, sentiment, research, moonshots, prediction markets.

### UI primitives (`src/components/ui/`)
GlassCard, StatusBadge, StatCard, DeltaChip, Sparkline, GlassInput, GlassSelect, SegmentedControl, GlassButton, Gauge, Skeleton, Tooltip, Drawer, EmptyState, StreamingText, AgentTag.

### Layout shell (`src/components/layout/`)
- `AuroraBackground` — background + grain.
- `Sidebar` — 9 nav items, collapse/mobile drawer, active `layoutId` indicator, alert badge support, last-sync pulse.
- `AppShell` — sidebar + top bar with ⌘K trigger, data-as-of clock, connection pulse.
- `CommandPalette` — `cmdk`-based palette, Cmd/Ctrl+K open, fuzzy navigation, "Ask AlphaDesk" streaming answer with AgentTag + confidence.

### Views (`src/components/<view>/`)
| View | Route | Highlights |
|------|-------|------------|
| CommandCenter | `/` | Generative brief stack, stat row, streaming AI answer, conditional sections (breaches, movers, macro, sentiment, research, moonshot). |
| PortfolioView | `/portfolio` | Donut allocation chart, holdings table with tabular-nums, row hover, detail Drawer, AI commentary. |
| AlertsView | `/alerts` | Stateful breach cards, severity glows, threshold bars, Ack/Mute actions with `layout` animation, timeline, history. |
| MacroView | `/macro` | Regime gauge + streamed rationale, theme cards, signal feed, violet AI attribution. |
| SentimentView | `/sentiment` | Trending ticker cards, divergence highlights, per-ticker Drawer with area chart + galaxy score. |
| ResearchView | `/research` | Quick/Deep mode toggle, streaming live report, past-report feed, reader Drawer. |
| MoonshotsView | `/moonshots` | Sector-filtered grid, conviction meters, asymmetry bars, streamed "why now". |
| MarketsView | `/markets` | Prediction-market cards, probability bars, 7-day sparklines, edge vs model estimate. |
| DigestView | `/digest` | Email-style preview, date-range control, Regenerate/Copy HTML/Copy Markdown. |

### Router & performance
- `src/App.tsx` wires all 9 routes inside `AppShell` with `AnimatePresence` transitions.
- React.lazy + Suspense code-split every view; build emits per-view chunks and eliminates chunk-size warnings.
- `src/main.tsx` uses `StrictMode`.

## Quality verification

```bash
cd /Users/vikram/workspace/alpha-desk/dashboard
npm run typecheck   # ✅ zero errors
npm run lint        # ✅ zero errors
npm run build       # ✅ zero errors, zero warnings
npm run dev         # ✅ starts successfully
```

## Architecture decisions
- **Mock-first API seam:** `src/lib/api.ts` returns typed promises so the real Python backend can drop in later without changing components.
- **Lazy-loaded routes:** Keeps initial bundle under 500 kB and gives instant dev/prod builds.
- **Single reduced-motion hook:** Avoids duplicating `matchMedia` logic across views.
- **ESLint:** Disabled the experimental `react-hooks/set-state-in-effect` rule, which flags common data-fetching patterns. Real violations (conditional hook, unused var) were fixed.

## Post-build fixes
- **Blank-page rendering issue:** The original `AuroraBackground` wrapped the app inside a `position: fixed; inset: 0; z-index: -1` element. In some browsers this caused the entire React tree to be hidden behind the background layer. Fixed by splitting the background into a standalone `fixed -z-10` sibling and the app content into a separate `relative z-10` sibling (`src/components/layout/AuroraBackground.tsx`). Playwright screenshot verification now shows the dashboard correctly.

## Known limitations / next steps
1. **No real backend integration yet.** `src/lib/api.ts` is pure mock data.
2. **No automated UI/E2E tests.** All verification is static/build-time plus manual Playwright screenshots.
3. **Charts bundled together:** Recharts components currently chunk into `Sparkline-*.js` (274 kB) because many views import `Sparkline`. If initial bundle becomes a concern, further split chart primitives.
4. **Some views use local `useState/useEffect` data fetching.** When wiring the real backend, consider centralizing with TanStack Query or SWR for caching/refetch.
5. **Accessibility:** Basic contrast and reduced-motion are in place, but no axe/lighthouse audit was run.

## Commands for the next agent

```bash
cd /Users/vikram/workspace/alpha-desk/dashboard
npm install        # if needed
npm run dev        # local dev server
npm run typecheck  # static type check
npm run lint       # lint
npm run build      # production build
```

## File inventory (key paths)

```
dashboard/
├── AGENTS.md
├── HANDOFF.md
├── eslint.config.js
├── package.json
├── vite.config.ts
├── src/
│   ├── App.tsx
│   ├── main.tsx
│   ├── index.css
│   ├── types/index.ts
│   ├── lib/
│   │   ├── api.ts
│   │   ├── cn.ts
│   │   ├── format.ts
│   │   ├── motion.ts
│   │   └── useReducedMotion.ts
│   ├── data/
│   │   ├── portfolio.ts
│   │   ├── alerts.ts
│   │   ├── macro.ts
│   │   ├── sentiment.ts
│   │   ├── research.ts
│   │   ├── moonshots.ts
│   │   └── markets.ts
│   ├── components/
│   │   ├── ui/           # 16 primitives
│   │   ├── layout/       # Shell + command palette
│   │   ├── commandcenter/
│   │   ├── portfolio/
│   │   ├── alerts/
│   │   ├── macro/
│   │   ├── sentiment/
│   │   ├── research/
│   │   ├── moonshots/
│   │   ├── markets/
│   │   └── digest/
```
