import { storedFlag } from "@/lib/storedFlag";

const flag = storedFlag("mayedge-chart-axis-ticket");

export const getAxisTicketArmed = flag.get;
export const setAxisTicketArmed = flag.set;
export const subscribeAxisTicket = flag.subscribe;

export function useAxisTicket() {
  const [armed, setArmed] = flag.useFlag();
  return { armed, setArmed };
}
