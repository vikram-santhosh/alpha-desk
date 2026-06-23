import { AnimatePresence, motion } from "motion/react";
import { Suspense, lazy, useState } from "react";
import {
  BrowserRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { Skeleton } from "@/components/ui/Skeleton";

const AlertsView = lazy(() => import("@/components/alerts/AlertsView"));
const CommandCenter = lazy(() => import("@/components/commandcenter/CommandCenter"));
const DigestView = lazy(() => import("@/components/digest/DigestView"));
const MacroView = lazy(() => import("@/components/macro/MacroView"));
const MarketsView = lazy(() => import("@/components/markets/MarketsView"));
const MoonshotsView = lazy(() => import("@/components/moonshots/MoonshotsView"));
const PortfolioView = lazy(() => import("@/components/portfolio/PortfolioView"));
const ResearchView = lazy(() => import("@/components/research/ResearchView"));
const SentimentView = lazy(() => import("@/components/sentiment/SentimentView"));

const routeToNavId: Record<string, string> = {
  "/": "dashboard",
  "/portfolio": "portfolio",
  "/alerts": "alerts",
  "/macro": "macro",
  "/sentiment": "sentiment",
  "/research": "research",
  "/moonshots": "moonshots",
  "/markets": "markets",
  "/digest": "digest",
};

const navIdToRoute: Record<string, string> = Object.fromEntries(
  Object.entries(routeToNavId).map(([route, id]) => [id, route])
);

function PageLoader() {
  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
      <Skeleton className="h-8 w-56" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
      <Skeleton className="h-96" />
    </div>
  );
}

function AppRouter() {
  const location = useLocation();
  const navigate = useNavigate();
  const [commandOpen, setCommandOpen] = useState(false);

  const activeNavId = routeToNavId[location.pathname] ?? "dashboard";

  const handleNavigate = (id: string) => {
    const route = navIdToRoute[id];
    if (route) navigate(route);
  };

  return (
    <AppShell
      activeNavId={activeNavId}
      onNavigate={handleNavigate}
      onOpenCommandPalette={() => setCommandOpen(true)}
    >
      <CommandPalette
        open={commandOpen}
        onClose={() => setCommandOpen(false)}
        onNavigate={handleNavigate}
      />
      <AnimatePresence mode="wait">
        <motion.div
          key={location.pathname}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25 }}
        >
          <Suspense fallback={<PageLoader />}>
            <Routes location={location}>
              <Route path="/" element={<CommandCenter />} />
              <Route path="/portfolio" element={<PortfolioView />} />
              <Route path="/alerts" element={<AlertsView />} />
              <Route path="/macro" element={<MacroView />} />
              <Route path="/sentiment" element={<SentimentView />} />
              <Route path="/research" element={<ResearchView />} />
              <Route path="/moonshots" element={<MoonshotsView />} />
              <Route path="/markets" element={<MarketsView />} />
              <Route path="/digest" element={<DigestView />} />
            </Routes>
          </Suspense>
        </motion.div>
      </AnimatePresence>
    </AppShell>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppRouter />
    </BrowserRouter>
  );
}

export default App;
