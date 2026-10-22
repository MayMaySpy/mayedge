import { lazy, Suspense } from "react";
import { Dashboard } from "@/components/Dashboard";
import { WatchPopout } from "@/components/WatchPopout";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { isIdeasPath, isJournalPath, isPortfolioPath, isWatchPath } from "@/lib/deskRoute";

const JournalPage = lazy(() => import("@/components/JournalPage").then((m) => ({ default: m.JournalPage })));
const PortfolioPage = lazy(() => import("@/components/PortfolioPage").then((m) => ({ default: m.PortfolioPage })));
const IdeasPage = lazy(() => import("@/components/IdeasPage").then((m) => ({ default: m.IdeasPage })));

function App() {
  const path = window.location.pathname;
  const watch = isWatchPath(path);
  const journal = isJournalPath(path);
  const portfolio = isPortfolioPath(path);
  const ideas = isIdeasPath(path);
  return (
    <TooltipProvider>
      {watch ? (
        <WatchPopout />
      ) : journal ? (
        <Suspense fallback={null}>
          <JournalPage />
        </Suspense>
      ) : portfolio ? (
        <Suspense fallback={null}>
          <PortfolioPage />
        </Suspense>
      ) : ideas ? (
        <Suspense fallback={null}>
          <IdeasPage />
        </Suspense>
      ) : (
        <Dashboard />
      )}
      {!watch ? <Toaster /> : null}
    </TooltipProvider>
  );
}

export default App;
