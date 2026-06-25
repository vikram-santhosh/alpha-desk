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

const BackendCockpitView = lazy(() => import("@/components/backend/BackendCockpitView"));
const CouncilView = lazy(() => import("@/components/council/CouncilView"));
const MacroView = lazy(() => import("@/components/macro/MacroView"));
const TopBuysView = lazy(() => import("@/components/scout/TopBuysView"));
const PortfolioView = lazy(() => import("@/components/portfolio/BackendPortfolioView"));

const routeToNavId: Record<string, string> = {
  "/": "dashboard",
  "/scout": "scout",
  "/council": "council",
  "/portfolio": "portfolio",
  "/macro": "macro",
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
              <Route path="/" element={<BackendCockpitView />} />
              <Route path="/scout" element={<TopBuysView />} />
              <Route path="/council" element={<CouncilView />} />
              <Route path="/portfolio" element={<PortfolioView />} />
              <Route path="/macro" element={<MacroView />} />
              <Route path="*" element={<BackendCockpitView />} />
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
