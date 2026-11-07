import type { AlgoBandEntry } from "./types";

/** Lockstep with backend `algos/massager/config.py` (ADR 0004). */
export const MASSAGER_COI_BASE = 13_000_000_000;
export const MASSAGER_COI_END = 14_000_000_000;

/**
 * The Massager's ticket comes in phase 4 (docs/massager-scope.md). Until then it
 * owns a client_order_index band and a label, so its Clips read as Massager.
 */
export const massagerBand: AlgoBandEntry = {
  id: "massager",
  label: "Massager",
  deskType: "massager",
  coi: { base: MASSAGER_COI_BASE, end: MASSAGER_COI_END },
};
