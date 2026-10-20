import { lazy, Suspense } from "react";
import { Dashboard } from "@/components/Dashboard";
import { WatchPopout } from "@/components/WatchPopout";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { isJournalPath, isWatchPath } from "@/lib/deskRoute";

const JournalPage = lazy(() => import("@/components/JournalPage").then((m) => ({ default: m.JournalPage })));

function App() {
  const path = window.location.pathname;
  const watch = isWatchPath(path);
  const journal = isJournalPath(path);
  return (
    <TooltipProvider>
      {watch ? (
        <WatchPopout />
      ) : journal ? (
        <Suspense fallback={null}>
          <JournalPage />
        </Suspense>
      ) : (
        <Dashboard />
      )}
      {!watch ? <Toaster /> : null}
    </TooltipProvider>
  );
}

export default App;
