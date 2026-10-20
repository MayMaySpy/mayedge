/** The desk keymap. The help sheet and the hook both read this. */

export type HotkeyId =
  | "buy"
  | "sell"
  | "cancel"
  | "kill"
  | "tf-1"
  | "tf-2"
  | "tf-3"
  | "tf-4"
  | "tf-5"
  | "tf-6"
  | "tf-7"
  | "picker"
  | "favorite"
  | "chart"
  | "scan"
  | "watch"
  | "axis"
  | "planner"
  | "escape"
  | "help";

/** These send or cancel orders, and do nothing until hotkey trading is armed. */
export const TRADING_HOTKEYS = new Set<HotkeyId>(["buy", "sell", "cancel"]);

export const HOTKEY_EVENT = "mayedge-hotkey";

export const HOTKEY_SHEET: { keys: string; action: string }[] = [
  { keys: "Shift+B / Shift+S", action: "Market buy / sell at Quick size" },
  { keys: "Shift+X", action: "Cancel this Market's Tickets" },
  { keys: "Shift+K", action: "Open Kill" },
  { keys: "1–7", action: "Pinned timeframe" },
  { keys: "/ or ⌘K", action: "Market picker" },
  { keys: "F", action: "Favorite this Market" },
  { keys: "C / S / W", action: "Chart / Scan / Watch" },
  { keys: "A", action: "Arm or disarm Axis" },
  { keys: "P", action: "Open Planner" },
  { keys: "Esc", action: "Cancel a drag or edit" },
  { keys: "?", action: "This sheet" },
];

export interface HotkeyPress {
  code: string;
  key: string;
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
}

export function matchHotkey(press: HotkeyPress): HotkeyId | null {
  if (press.altKey) return null;
  const mod = press.metaKey || press.ctrlKey;
  if (press.code === "Escape" && !mod && !press.shiftKey) return "escape";
  if (press.code === "KeyK" && mod && !press.shiftKey) return "picker";
  if (mod) return null;
  if (press.shiftKey) {
    if (press.code === "KeyB") return "buy";
    if (press.code === "KeyS") return "sell";
    if (press.code === "KeyX") return "cancel";
    if (press.code === "KeyK") return "kill";
    if (press.code === "Slash" || press.key === "?") return "help";
    return null;
  }
  if (press.code === "Slash" || press.key === "/") return "picker";
  if (press.key === "?") return "help";
  const digit = /^Digit([1-7])$/.exec(press.code);
  if (digit) return `tf-${digit[1]}` as HotkeyId;
  switch (press.code) {
    case "KeyF":
      return "favorite";
    case "KeyC":
      return "chart";
    case "KeyS":
      return "scan";
    case "KeyW":
      return "watch";
    case "KeyA":
      return "axis";
    case "KeyP":
      return "planner";
    default:
      return null;
  }
}

export function hotkeyBlocked(target: EventTarget | null, root: ParentNode = document): boolean {
  if (target instanceof Element && target.closest("input, textarea, select, [contenteditable='true']")) {
    return true;
  }
  return (
    root.querySelector(
      "[role='dialog'][data-state='open'], [data-slot='popover-content'][data-state='open']",
    ) != null
  );
}

export function emitHotkey(id: HotkeyId) {
  window.dispatchEvent(new CustomEvent(HOTKEY_EVENT, { detail: id }));
}

export function subscribeHotkeys(onAction: (id: HotkeyId) => void): () => void {
  const onEvent = (event: Event) => onAction((event as CustomEvent<HotkeyId>).detail);
  window.addEventListener(HOTKEY_EVENT, onEvent);
  return () => window.removeEventListener(HOTKEY_EVENT, onEvent);
}
