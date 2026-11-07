import { chaseGridPlugin } from "./chaseGridPlugin";
import { chaseIcebergPlugin } from "./chaseIcebergPlugin";
import { ladderPlugin } from "./ladderPlugin";
import { massagerPlugin } from "./massagerPlugin";
import { plannerBand } from "./plannerBand";
import { trailPlugin } from "./trailPlugin";
import { twapPlugin } from "./twapPlugin";
import { coiInBand, type AlgoBandEntry, type AlgoCoiBand, type AlgoPlugin } from "./types";

export const ALGO_PLUGINS = [
  twapPlugin,
  chaseIcebergPlugin,
  chaseGridPlugin,
  ladderPlugin,
  trailPlugin,
  massagerPlugin,
] as const;

const COI_PLUGINS: readonly AlgoBandEntry[] = [...ALGO_PLUGINS, plannerBand];

export type AlgoId = (typeof ALGO_PLUGINS)[number]["id"];

export type {
  AlgoBandEntry,
  AlgoBlockContext,
  AlgoCoiBand,
  AlgoPlugin,
  AlgoSubmitContext,
} from "./types";
export { coiInBand };
export {
  CHASE_COI_BASE,
  CHASE_COI_END,
  chaseIcebergPlugin,
} from "./chaseIcebergPlugin";
export { GRID_COI_BASE, GRID_COI_END, chaseGridPlugin } from "./chaseGridPlugin";
export { LADDER_COI_BASE, LADDER_COI_END, ladderPlugin } from "./ladderPlugin";
export { PLANNER_COI_BASE, PLANNER_COI_END, plannerBand } from "./plannerBand";
export { MASSAGER_COI_BASE, MASSAGER_COI_END, massagerPlugin } from "./massagerPlugin";
export { TRAIL_COI_BASE, TRAIL_COI_END, trailPlugin } from "./trailPlugin";
export { TWAP_COI_BASE, TWAP_COI_END, twapPlugin } from "./twapPlugin";

export function algoPluginById(id: string): AlgoPlugin | undefined {
  return ALGO_PLUGINS.find((p) => p.id === id) as AlgoPlugin | undefined;
}

export function algoPluginByDeskType(deskType: string): AlgoBandEntry | undefined {
  return COI_PLUGINS.find((p) => p.deskType === deskType || p.id === deskType);
}

export function algoPluginByCoi(coi: string | number | null | undefined) {
  for (const plugin of COI_PLUGINS) {
    if (plugin.coi && coiInBand(coi, plugin.coi)) return plugin;
  }
  return undefined;
}

export function algoCoiBands(): AlgoCoiBand[] {
  return COI_PLUGINS.flatMap((p) => (p.coi ? [p.coi] : []));
}

export function isAlgoClientOrder(coi: string | number | null | undefined): boolean {
  return algoPluginByCoi(coi) != null;
}

export function algoOrderKind(
  coi: string | number | null | undefined,
  opts?: { gridTakeProfits?: ReadonlySet<string> }
): string | null {
  const plugin = algoPluginByCoi(coi);
  if (!plugin) return null;
  if (plugin.id === "chase-grid" && coi != null && opts?.gridTakeProfits?.has(String(coi))) {
    return "Grid TP";
  }
  return plugin.label;
}

/** Live Grid take-profit Clips by client_order_index. Grid's Clips are never reduce-only (grid-rules G3), so only the book's clip kind tells them apart. */
export function gridTakeProfitCois(
  working: readonly { algo_type?: string | null; clips?: readonly { client_order_index: string | number; status: string; kind?: string | null }[] }[]
): Set<string> {
  const out = new Set<string>();
  for (const algo of working) {
    if (algo.algo_type !== "chase-grid") continue;
    for (const clip of algo.clips ?? []) {
      if (clip.kind === "tp" && clip.status === "live") out.add(String(clip.client_order_index));
    }
  }
  return out;
}

/** Catalog row for pickers — derived from plugins. */
export const ALGOS = ALGO_PLUGINS.map((p) => ({
  id: p.id as AlgoId,
  label: p.label,
  intent: p.intent,
}));

export function algoById(id: AlgoId) {
  const plugin = algoPluginById(id);
  return plugin
    ? { id: plugin.id as AlgoId, label: plugin.label, intent: plugin.intent }
    : ALGOS[0];
}

export function algoLabelForType(algoType: string | null | undefined): string {
  if (!algoType) return "Algo";
  return algoPluginByDeskType(algoType)?.label ?? algoType;
}

export function isAlgoChildOrder(
  order: { client_order_index: string | number },
  algo?: {
    working_coi?: number | null;
    clips?: { client_order_index: number; status: string }[] | null;
  } | null
): boolean {
  if (isAlgoClientOrder(order.client_order_index)) return true;
  if (!algo) return false;
  const coi = Number(order.client_order_index);
  if (algo.working_coi != null && coi === algo.working_coi) return true;
  return (algo.clips ?? []).some(
    (c) => c.status === "live" && c.client_order_index === coi
  );
}
