// @vitest-environment jsdom
import "@/test/dom";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useHotkeys } from "@/hooks/useHotkeys";

function Probe({ armed, onAction }: { armed: boolean; onAction: (id: string) => void }) {
  useHotkeys(armed, onAction);
  return null;
}

function key(code: string, init: KeyboardEventInit = {}) {
  window.dispatchEvent(new KeyboardEvent("keydown", { code, bubbles: true, ...init }));
}

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("useHotkeys", () => {
  it("does nothing with trading keys while disarmed, and calls once while armed", () => {
    const onAction = vi.fn();
    const view = render(<Probe armed={false} onAction={onAction} />);
    key("KeyB", { shiftKey: true });
    key("KeyB", { shiftKey: true, repeat: true });
    expect(onAction).not.toHaveBeenCalled();

    view.rerender(<Probe armed onAction={onAction} />);
    key("KeyB", { shiftKey: true });
    key("KeyB", { shiftKey: true, repeat: true });
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith("buy");
  });

  it("opens Kill and does not send an order", () => {
    const onAction = vi.fn();
    render(<Probe armed={false} onAction={onAction} />);
    key("KeyK", { shiftKey: true });
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith("kill");
    expect(onAction).not.toHaveBeenCalledWith("buy");
    expect(onAction).not.toHaveBeenCalledWith("sell");
    expect(onAction).not.toHaveBeenCalledWith("cancel");
  });

  it("ignores a key while a dialog is open", () => {
    document.body.innerHTML = `<div role="dialog" data-state="open"></div>`;
    const onAction = vi.fn();
    render(<Probe armed onAction={onAction} />);
    key("KeyF");
    expect(onAction).not.toHaveBeenCalled();
  });
});
