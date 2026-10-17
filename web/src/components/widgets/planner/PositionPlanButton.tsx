import { useState } from "react";
import { Button } from "@/components/ui/button";
import { PlannerDialog } from "@/components/widgets/planner/PlannerDialog";
import { isLongPosition, type AlgoState, type Market, type Position } from "@/lib/api";

/** Attach a Planner to an open Position, or re-plan the one that holds it. */
export function PositionPlanButton({
  position,
  market,
  running,
  disabled,
}: {
  position: Position;
  market: Market | null;
  running?: AlgoState;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (!market || market.market_index !== position.market_index) return null;
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-6 px-1.5"
        disabled={disabled}
        title={running ? "Planner owns this exit: re-plan it" : "Plan this Position's exit"}
        onClick={() => setOpen(true)}
      >
        {running ? "Re-plan" : "Plan"}
      </Button>
      <PlannerDialog
        open={open}
        onOpenChange={setOpen}
        market={market}
        mode="attach"
        side={isLongPosition(position) ? "buy" : "sell"}
        running={running}
      />
    </>
  );
}
