import { SlipControl } from "../ui";

interface MarketParamsProps {
  slippagePct: string;
  worst: number | null;
  onSlipChange: (raw: string) => void;
}

/** Add new top-level kinds beside this file under `kinds/`. */
export function MarketParams({ slippagePct, worst, onSlipChange }: MarketParamsProps) {
  return <SlipControl slippagePct={slippagePct} worst={worst} onChange={onSlipChange} />;
}
