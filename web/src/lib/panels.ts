export const PANEL_IDS = [
  "chart",
  "book",
  "tape",
  "ticket",
  "alerts",
  "liqs",
  "positions",
] as const;

export type PanelId = (typeof PANEL_IDS)[number];

/** Human titles — must match on-panel chrome. */
export const PANEL_CATALOG: Record<PanelId, string> = {
  chart: "Chart",
  book: "Book",
  tape: "Trades",
  ticket: "Order",
  alerts: "Alerts",
  liqs: "Liqs",
  positions: "Positions",
};

export function defaultPanelVisibility(): Record<PanelId, boolean> {
  return Object.fromEntries(PANEL_IDS.map((id) => [id, true])) as Record<PanelId, boolean>;
}
