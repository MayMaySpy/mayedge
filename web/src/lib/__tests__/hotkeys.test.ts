// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { HOTKEY_SHEET, hotkeyBlocked, matchHotkey, type HotkeyPress } from "@/lib/hotkeys";

function press(partial: Partial<HotkeyPress> & Pick<HotkeyPress, "code">): HotkeyPress {
  return {
    key: "",
    shiftKey: false,
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    ...partial,
  };
}

describe("matchHotkey", () => {
  it("maps the desk keys, and Shift changes S from Scan to sell", () => {
    expect(matchHotkey(press({ code: "KeyS" }))).toBe("scan");
    expect(matchHotkey(press({ code: "KeyS", shiftKey: true }))).toBe("sell");
    expect(matchHotkey(press({ code: "KeyB", shiftKey: true }))).toBe("buy");
    expect(matchHotkey(press({ code: "KeyX", shiftKey: true }))).toBe("cancel");
    expect(matchHotkey(press({ code: "KeyK", shiftKey: true }))).toBe("kill");
    expect(matchHotkey(press({ code: "Digit3" }))).toBe("tf-3");
    expect(matchHotkey(press({ code: "Slash", key: "/" }))).toBe("picker");
    expect(matchHotkey(press({ code: "KeyK", metaKey: true }))).toBe("picker");
    expect(matchHotkey(press({ code: "KeyF" }))).toBe("favorite");
    expect(matchHotkey(press({ code: "KeyC" }))).toBe("chart");
    expect(matchHotkey(press({ code: "KeyW" }))).toBe("watch");
    expect(matchHotkey(press({ code: "KeyA" }))).toBe("axis");
    expect(matchHotkey(press({ code: "KeyP" }))).toBe("planner");
    expect(matchHotkey(press({ code: "Escape" }))).toBe("escape");
    expect(matchHotkey(press({ code: "Slash", key: "?", shiftKey: true }))).toBe("help");
    expect(matchHotkey(press({ code: "KeyB" }))).toBeNull();
  });

  it("lists every key on the sheet", () => {
    const text = HOTKEY_SHEET.map((row) => row.keys).join(" ");
    for (const label of ["Shift+B", "Shift+S", "Shift+X", "Shift+K", "1–7", "F", "C", "S", "W", "A", "P", "Esc", "?"]) {
      expect(text).toContain(label);
    }
  });
});

describe("hotkeyBlocked", () => {
  it("ignores typing in a field and an open dialog", () => {
    document.body.innerHTML = `<div><input id="size" /><div role="dialog" data-state="closed"></div></div>`;
    const input = document.getElementById("size");
    expect(hotkeyBlocked(input)).toBe(true);
    expect(hotkeyBlocked(document.body)).toBe(false);
    document.body.innerHTML = `<div role="dialog" data-state="open"></div>`;
    expect(hotkeyBlocked(document.body)).toBe(true);
    document.body.innerHTML = "";
  });
});
