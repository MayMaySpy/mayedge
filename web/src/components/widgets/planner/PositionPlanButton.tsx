import { lazy, Suspense, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { isLongPosition, type AlgoState, type Market, type Position } from "@/lib/api";

const PlannerDialog = lazy(() =>
  import("@/components/widgets/planner/PlannerDialog").then((m) => ({ default: m.PlannerDialog })),
);

function PlannerDialogFallback({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Planner</DialogTitle>
          <DialogDescription>One trade from its stop.</DialogDescription>
        </DialogHeader>
      </DialogContent>
    </Dialog>
  );
}

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
      {open ? (
        <Suspense fallback={<PlannerDialogFallback onOpenChange={setOpen} />}>
          <PlannerDialog
            open={open}
            onOpenChange={setOpen}
            market={market}
            mode="attach"
            side={isLongPosition(position) ? "buy" : "sell"}
            running={running}
          />
        </Suspense>
      ) : null}
    </>
  );
}
