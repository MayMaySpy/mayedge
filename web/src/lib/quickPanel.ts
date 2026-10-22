import { storedFlag } from "@/lib/storedFlag";

const flag = storedFlag("mayedge-chart-quick");

export const getQuickPanelOpen = flag.get;
export const setQuickPanelOpen = flag.set;
export const subscribeQuickPanel = flag.subscribe;

export function useQuickPanel() {
  const [open, setOpen] = flag.useFlag();
  return { open, setOpen };
}
