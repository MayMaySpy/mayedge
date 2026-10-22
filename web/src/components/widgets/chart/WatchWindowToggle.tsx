import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { persistWatchWindow, WATCH_WINDOWS, type WatchWindow } from "@/lib/watchWindow";

/** The Watch path window: 15m, 1h or 4h. A new pick is kept for the next visit. */
export function WatchWindowToggle({
  value,
  onChange,
}: {
  value: WatchWindow;
  onChange: (next: WatchWindow) => void;
}) {
  return (
    <ToggleGroup
      type="single"
      size="sm"
      spacing={0}
      value={value}
      onValueChange={(v) => {
        if (!v || v === value || !(WATCH_WINDOWS as readonly string[]).includes(v)) return;
        onChange(v as WatchWindow);
        persistWatchWindow(v as WatchWindow);
      }}
    >
      {WATCH_WINDOWS.map((w) => (
        <ToggleGroupItem
          key={w}
          value={w}
          title="Path window"
          className="h-5 rounded-sm px-1.5 font-mono text-xs data-[state=on]:bg-rule"
        >
          {w}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
