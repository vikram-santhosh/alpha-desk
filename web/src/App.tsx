import { AnimatePresence, motion } from "motion/react";
import { Suspense, lazy } from "react";
import {
  BrowserRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { Skeleton } from "@/components/ui/Skeleton";

const BriefView = lazy(() => import("@/components/brief/BriefView"));
const CouncilView = lazy(() => import("@/components/council/CouncilView"));
const MacroView = lazy(() => import("@/components/macro/MacroView"));
const TopBuysView = lazy(() => import("@/components/scout/TopBuysView"));
const DeploymentView = lazy(() => import("@/components/deployment/DeploymentView"));
const PortfolioView = lazy(() => import("@/components/portfolio/BackendPortfolioView"));
const MarketsView = lazy(() => import("@/components/markets/MarketsView"));
const ResearchView = lazy(() => import("@/components/research/ResearchView"));
const MoonshotsView = lazy(() => import("@/components/moonshots/MoonshotsView"));
const AlertsView = lazy(() => import("@/components/alerts/AlertsView"));
const SentimentView = lazy(() => import("@/components/sentiment/SentimentView"));

const routeToNavId: Record<string, string> = {
  "/": "dashboard",
  "/scout": "scout",
  "/deployment": "deployment",
  "/council": "council",
  "/research": "research",
  "/moonshots": "moonshots",
  "/portfolio": "portfolio",
  "/macro": "macro",
  "/markets": "markets",
  "/sentiment": "sentiment",
  "/alerts": "alerts",
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

  const activeNavId = routeToNavId[location.pathname] ?? "dashboard";

  const handleNavigate = (id: string) => {
    const route = navIdToRoute[id];
    if (route) navigate(route);
  };

  return (
    <AppShell
      activeNavId={activeNavId}
      onNavigate={handleNavigate}
    >
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
              <Route path="/" element={<BriefView />} />
              <Route path="/scout" element={<TopBuysView />} />
              <Route path="/deployment" element={<DeploymentView />} />
              <Route path="/council" element={<CouncilView />} />
              <Route path="/research" element={<ResearchView />} />
              <Route path="/moonshots" element={<MoonshotsView />} />
              <Route path="/markets" element={<MarketsView />} />
              <Route path="/sentiment" element={<SentimentView />} />
              <Route path="/alerts" element={<AlertsView />} />
              <Route path="/portfolio" element={<PortfolioView />} />
              <Route path="/macro" element={<MacroView />} />
              <Route path="*" element={<BriefView />} />
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
