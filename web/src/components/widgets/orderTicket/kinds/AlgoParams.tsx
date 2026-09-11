import type { ComponentType } from "react";
import { algoPluginById, type AlgoId } from "@/lib/algoPlugins";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import type { Market } from "@/lib/api";

interface AlgoParamsProps {
  algo: AlgoId;
  market: Market;
  bookMid: number | null;
  sizeNum: number;
  pluginState: unknown;
  onPluginStateChange: (state: unknown) => void;
}

export function AlgoParams({
  algo,
  market,
  bookMid,
  sizeNum,
  pluginState,
  onPluginStateChange,
}: AlgoParamsProps) {
  const plugin = algoPluginById(algo);
  if (!plugin) return null;
  const Sheet = plugin.ParamsSheet as ComponentType<AlgoParamsSheetProps<unknown>>;
  return (
    <Sheet
      market={market}
      bookMid={bookMid}
      sizeNum={sizeNum}
      state={pluginState}
      onStateChange={onPluginStateChange}
    />
  );
}
