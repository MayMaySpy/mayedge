import type { AlgoBandEntry } from "./types";

/** Lockstep with backend `algos/planner/config.py` (ADR 0004). */
export const PLANNER_COI_BASE = 11_000_000_000;
export const PLANNER_COI_END = 12_000_000_000;

/**
 * Planner has its own dialog, not a ticket sheet, so it is not in the Algo
 * dropdown. It still owns a client_order_index band and a label.
 */
export const plannerBand: AlgoBandEntry = {
  id: "planner",
  label: "Planner",
  deskType: "planner",
  coi: { base: PLANNER_COI_BASE, end: PLANNER_COI_END },
};
