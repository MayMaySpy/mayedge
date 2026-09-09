import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { FieldGroup } from "@/components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@/components/ui/input-group";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useEffect, useRef } from "react";
import { leverageAnchors, snapLeverage } from "./math";

interface LeverageModalProps {
  open: boolean;
  symbol: string;
  lev: number;
  presets: number[];
  maxLev: number;
  draft: string;
  loading: boolean;
  tradingEnabled: boolean;
  onDraftChange: (raw: string) => void;
  onClose: () => void;
  onApply: (value: string) => void;
}

export function LeverageModal({
  open,
  symbol,
  lev,
  presets,
  maxLev,
  draft,
  loading,
  tradingEnabled,
  onDraftChange,
  onClose,
  onApply,
}: LeverageModalProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const anchors = leverageAnchors(presets);
  const snappedDraft = snapLeverage(presets, draft);
  const draftDirty = snappedDraft != null && String(snappedDraft) !== draft.trim();

  useEffect(() => {
    if (!open) return;
    const id = requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    });
    return () => cancelAnimationFrame(id);
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent showCloseButton={false} className="w-72 gap-2 sm:max-w-72">
        <DialogHeader className="flex-row items-baseline justify-between gap-2">
          <DialogTitle>Leverage</DialogTitle>
          <DialogDescription>
            {presets[0]}–{maxLev}x on {symbol}
          </DialogDescription>
        </DialogHeader>
        <FieldGroup className="gap-2">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onApply(draft);
            }}
            className="flex items-center gap-1.5"
          >
            <InputGroup className="h-9 flex-1">
              <InputGroupInput
                ref={inputRef}
                inputMode="numeric"
                value={draft}
                onChange={(e) => onDraftChange(e.target.value.replace(/[^\d]/g, ""))}
                className="font-mono text-sm tabular-nums"
                aria-label="Leverage"
              />
              <InputGroupAddon align="inline-end">
                <InputGroupText className="font-mono text-sm">x</InputGroupText>
              </InputGroupAddon>
            </InputGroup>
            <Button type="submit" size="sm" disabled={loading || !tradingEnabled || !snappedDraft}>
              Set
            </Button>
          </form>
          {draftDirty && snappedDraft != null ? (
            <p className="text-[11px] text-muted">
              Snaps to <span className="font-mono tabular-nums text-text">{snappedDraft}x</span>
            </p>
          ) : null}
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            spacing={2}
            value={String(snappedDraft ?? lev)}
            onValueChange={(v) => {
              if (v) onDraftChange(v);
            }}
            className="flex-wrap"
            disabled={loading || !tradingEnabled}
          >
            {anchors.map((x) => (
              <ToggleGroupItem key={x} value={String(x)}>
                {x}x
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </FieldGroup>
      </DialogContent>
    </Dialog>
  );
}
