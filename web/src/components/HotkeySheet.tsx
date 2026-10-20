import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { HOTKEY_SHEET } from "@/lib/hotkeys";

export function HotkeySheet({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Hotkeys</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Shift+B, Shift+S and Shift+X send orders only while Hotkey trading is on in the Order panel.
        </p>
        <div className="flex flex-col gap-1 text-base">
          {HOTKEY_SHEET.map((row) => (
            <div key={row.keys} className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-2">
              <span className="font-mono text-sm">{row.keys}</span>
              <span>{row.action}</span>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
