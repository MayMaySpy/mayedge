import { FieldGroup } from "@/components/ui/field";
import type { AlgoParamsSheetProps } from "@/lib/algoPlugins/types";
import { BandFields, ClipOffsetFields } from "./ChaseFields";

export interface ChaseParamsState {
  displayQty: string;
  offsetBps: string;
  chaseFloor: string;
  chaseCeiling: string;
}

export function ChaseParamsSheet({
  market,
  bookMid,
  state,
  onStateChange,
}: AlgoParamsSheetProps<ChaseParamsState>) {
  const set = (patch: Partial<ChaseParamsState>) => onStateChange({ ...state, ...patch });

  return (
    <FieldGroup className="gap-3">
      <ClipOffsetFields
        idPrefix="algo"
        displayQty={state.displayQty}
        offsetBps={state.offsetBps}
        onChange={set}
      />
      <BandFields
        idPrefix="algo"
        market={market}
        bookMid={bookMid}
        floor={state.chaseFloor}
        ceiling={state.chaseCeiling}
        onChange={set}
      />
    </FieldGroup>
  );
}
