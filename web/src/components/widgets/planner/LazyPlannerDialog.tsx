import { lazy, Suspense, type ComponentProps } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

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

/** The Planner dialog, loaded the first time it opens. */
export function LazyPlannerDialog(props: ComponentProps<typeof PlannerDialog>) {
  if (!props.open) return null;
  return (
    <Suspense fallback={<PlannerDialogFallback onOpenChange={props.onOpenChange} />}>
      <PlannerDialog {...props} />
    </Suspense>
  );
}
