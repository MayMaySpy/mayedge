import { Toaster } from "sonner";
import { Dashboard } from "@/components/Dashboard";
import { TooltipProvider } from "@/components/ui/tooltip";

function App() {
  return (
    <TooltipProvider>
      <Dashboard />
      <Toaster theme="dark" position="bottom-right" richColors />
    </TooltipProvider>
  );
}

export default App;
