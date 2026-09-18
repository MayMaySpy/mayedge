import { Dashboard } from "@/components/Dashboard";
import { WatchPopout } from "@/components/WatchPopout";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { isWatchPath } from "@/lib/deskRoute";

function App() {
  const watch = isWatchPath(window.location.pathname);
  return (
    <TooltipProvider>
      {watch ? <WatchPopout /> : <Dashboard />}
      {!watch ? <Toaster /> : null}
    </TooltipProvider>
  );
}

export default App;
