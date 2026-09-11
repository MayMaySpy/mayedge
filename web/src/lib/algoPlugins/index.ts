import { chaseIcebergPlugin } from "./chaseIcebergPlugin";
import { ladderPlugin } from "./ladderPlugin";
import { twapPlugin } from "./twapPlugin";
import { coiInBand, type AlgoCoiBand, type AlgoPlugin } from "./types";

export const ALGO_PLUGINS = [twapPlugin, chaseIcebergPlugin, ladderPlugin] as const;

export type AlgoId = (typeof ALGO_PLUGINS)[number]["id"];

export type { AlgoBlockContext, AlgoCoiBand, AlgoPlugin, AlgoSubmitContext } from "./types";
export { coiInBand };
export {
  CHASE_COI_BASE,
  CHASE_COI_END,
  chaseIcebergPlugin,
} from "./chaseIcebergPlugin";
export { LADDER_COI_BASE, LADDER_COI_END, ladderPlugin } from "./ladderPlugin";
export { TWAP_COI_BASE, TWAP_COI_END, twapPlugin } from "./twapPlugin";

export function algoPluginById(id: string): AlgoPlugin | undefined {
  return ALGO_PLUGINS.find((p) => p.id === id) as AlgoPlugin | undefined;
}

export function algoPluginByDeskType(deskType: string): AlgoPlugin | undefined {
  return ALGO_PLUGINS.find((p) => p.deskType === deskType || p.id === deskType) as
    | AlgoPlugin
    | undefined;
}

export function algoPluginByCoi(coi: string | number | null | undefined) {
  for (const plugin of ALGO_PLUGINS) {
    if (plugin.coi && coiInBand(coi, plugin.coi)) return plugin;
  }
  return undefined;
}

export function algoCoiBands(): AlgoCoiBand[] {
  return ALGO_PLUGINS.flatMap((p) => (p.coi ? [p.coi] : []));
}

export function isAlgoClientOrder(coi: string | number | null | undefined): boolean {
  return algoPluginByCoi(coi) != null;
}

export function algoOrderKind(coi: string | number | null | undefined): string | null {
  return algoPluginByCoi(coi)?.label ?? null;
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
