import { Dashboard } from "@/components/Dashboard";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

function App() {
  return (
    <TooltipProvider>
      <Dashboard />
      <Toaster />
    </TooltipProvider>
  );
}

export default App;
