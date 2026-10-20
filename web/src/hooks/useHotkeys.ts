import { useEffect, useRef } from "react";
import { TRADING_HOTKEYS, hotkeyBlocked, matchHotkey, type HotkeyId } from "@/lib/hotkeys";

/** One listener for the desk. Trading keys stay quiet until armed, and a held key never repeats. */
export function useHotkeys(armed: boolean, onAction: (id: HotkeyId) => void) {
  const onActionRef = useRef(onAction);
  useEffect(() => {
    onActionRef.current = onAction;
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.repeat) return;
      if (hotkeyBlocked(event.target)) return;
      const id = matchHotkey(event);
      if (!id) return;
      if (TRADING_HOTKEYS.has(id) && !armed) return;
      if (id !== "escape") event.preventDefault();
      onActionRef.current(id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [armed]);
}
