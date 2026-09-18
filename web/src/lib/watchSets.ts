import { useSyncExternalStore } from "react";

const WATCH_DESK_KEY = "mayedge-watch-desk";
const WATCHLIST_KEY = "mayedge-watch";
export const WATCH_SET_CAP = 8;
export const WATCH_SET_MAX = 12;
const WATCH_PANE_COUNT = 4;

const EVENT = "mayedge-watch-desk";
const LAYOUTS = new Set([1, 2, 4]);

export type WatchLayout = 1 | 2 | 4;
export type WatchPanes = [string | null, string | null, string | null, string | null];

export type WatchSet = {
  id: string;
  name: string;
  symbols: string[];
};

export type WatchDesk = {
  sets: WatchSet[];
  layout: WatchLayout;
  panes: WatchPanes;
  labels: boolean;
};

let seq = 0;
let cache: WatchDesk | null = null;

function newSetId(): string {
  seq += 1;
  return `ws-${Date.now().toString(36)}-${seq}`;
}

function emptyWatchDesk(): WatchDesk {
  const id = newSetId();
  return {
    sets: [{ id, name: "Watch", symbols: [] }],
    layout: 1,
    panes: [id, null, null, null],
    labels: true,
  };
}

function asSymbols(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    if (typeof item !== "string" || !item || out.includes(item)) continue;
    out.push(item);
    if (out.length >= WATCH_SET_CAP) break;
  }
  return out;
}

function asName(value: unknown, fallback: string): string {
  if (typeof value !== "string") return fallback;
  const name = value.trim().slice(0, 24);
  return name || fallback;
}

function asLayout(value: unknown): WatchLayout {
  return LAYOUTS.has(value as number) ? (value as WatchLayout) : 1;
}

function normalizeSet(raw: unknown): WatchSet | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as { id?: unknown; name?: unknown; symbols?: unknown };
  const id = typeof row.id === "string" && row.id ? row.id : newSetId();
  return { id, name: asName(row.name, "Watch"), symbols: asSymbols(row.symbols) };
}

function normalizePanes(raw: unknown, sets: WatchSet[]): WatchPanes {
  const known = new Set(sets.map((s) => s.id));
  const src = Array.isArray(raw) ? raw : [];
  const panes: WatchPanes = [null, null, null, null];
  for (let i = 0; i < WATCH_PANE_COUNT; i++) {
    const id = src[i];
    panes[i] = typeof id === "string" && known.has(id) ? id : null;
  }
  if (panes[0] == null && sets[0]) panes[0] = sets[0].id;
  return panes;
}

function normalizeDesk(raw: unknown): WatchDesk | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as {
    sets?: unknown;
    layout?: unknown;
    panes?: unknown;
    labels?: unknown;
  };
  if (!Array.isArray(row.sets)) return null;
  const sets: WatchSet[] = [];
  const seen = new Set<string>();
  for (const item of row.sets) {
    const set = normalizeSet(item);
    if (!set || seen.has(set.id)) continue;
    seen.add(set.id);
    sets.push(set);
    if (sets.length >= WATCH_SET_MAX) break;
  }
  if (sets.length === 0) return null;
  return {
    sets,
    layout: asLayout(row.layout),
    panes: normalizePanes(row.panes, sets),
    labels: row.labels !== false,
  };
}

/** Build a Watch desk from persisted JSON, promoting a legacy Watchlist if needed. */
export function parseWatchStorage(deskRaw: string | null, legacyRaw: string | null): WatchDesk {
  if (deskRaw) {
    try {
      const desk = normalizeDesk(JSON.parse(deskRaw));
      if (desk) return desk;
    } catch {
      /* fall through */
    }
  }
  if (legacyRaw) {
    try {
      const symbols = asSymbols(JSON.parse(legacyRaw));
      const id = newSetId();
      return {
        sets: [{ id, name: "Watch", symbols }],
        layout: 1,
        panes: [id, null, null, null],
        labels: true,
      };
    } catch {
      /* fall through */
    }
  }
  return emptyWatchDesk();
}

function read(): WatchDesk {
  let deskRaw: string | null = null;
  let legacyRaw: string | null = null;
  try {
    deskRaw = localStorage.getItem(WATCH_DESK_KEY);
    legacyRaw = deskRaw ? null : localStorage.getItem(WATCHLIST_KEY);
  } catch {
    /* node tests */
  }
  const desk = parseWatchStorage(deskRaw, legacyRaw);
  cache = desk;
  if (!deskRaw && legacyRaw) persist(desk);
  return desk;
}

function persist(next: WatchDesk) {
  cache = next;
  try {
    localStorage.setItem(WATCH_DESK_KEY, JSON.stringify(next));
    localStorage.removeItem(WATCHLIST_KEY);
  } catch {
    /* node tests / private mode */
  }
  try {
    window.dispatchEvent(new Event(EVENT));
  } catch {
    /* node tests */
  }
}

function copyDesk(desk: WatchDesk): WatchDesk {
  return {
    sets: desk.sets.map((s) => ({ ...s, symbols: [...s.symbols] })),
    layout: desk.layout,
    panes: [...desk.panes],
    labels: desk.labels,
  };
}

export function getWatchDesk(): WatchDesk {
  return cache ?? read();
}

export function resetWatchDesk() {
  persist(emptyWatchDesk());
}

export function addToWatchSet(setId: string, symbol: string) {
  const desk = copyDesk(getWatchDesk());
  const set = desk.sets.find((s) => s.id === setId);
  if (!set || set.symbols.includes(symbol)) return;
  set.symbols = [symbol, ...set.symbols].slice(0, WATCH_SET_CAP);
  persist(desk);
}

export function removeFromWatchSet(setId: string, symbol: string) {
  const desk = copyDesk(getWatchDesk());
  const set = desk.sets.find((s) => s.id === setId);
  if (!set) return;
  set.symbols = set.symbols.filter((x) => x !== symbol);
  persist(desk);
}

export function createWatchSet(name?: string): string | null {
  const desk = copyDesk(getWatchDesk());
  if (desk.sets.length >= WATCH_SET_MAX) return null;
  const used = new Set(desk.sets.map((s) => s.id));
  let id = newSetId();
  while (used.has(id)) id = newSetId();
  const nextName = asName(name, desk.sets.length === 0 ? "Watch" : `Watch ${desk.sets.length + 1}`);
  desk.sets.push({ id, name: nextName, symbols: [] });
  persist(desk);
  return id;
}

export function renameWatchSet(setId: string, name: string) {
  const nextName = asName(name, "");
  if (!nextName) return;
  const desk = copyDesk(getWatchDesk());
  const set = desk.sets.find((s) => s.id === setId);
  if (!set) return;
  set.name = nextName;
  persist(desk);
}

export function deleteWatchSet(setId: string) {
  const desk = copyDesk(getWatchDesk());
  if (desk.sets.length <= 1) {
    const only = desk.sets[0];
    if (!only || only.id !== setId) return;
    only.name = "Watch";
    only.symbols = [];
    persist(desk);
    return;
  }
  desk.sets = desk.sets.filter((s) => s.id !== setId);
  desk.panes = desk.panes.map((id) => (id === setId ? null : id)) as WatchPanes;
  persist(desk);
}

export function setWatchLayout(layout: WatchLayout) {
  if (!LAYOUTS.has(layout)) return;
  const desk = copyDesk(getWatchDesk());
  desk.layout = layout;
  persist(desk);
}

export function assignWatchPane(index: number, setId: string | null) {
  if (index < 0 || index >= WATCH_PANE_COUNT) return;
  const desk = copyDesk(getWatchDesk());
  if (setId != null && !desk.sets.some((s) => s.id === setId)) return;
  desk.panes[index] = setId;
  if (index === 0 && setId == null && desk.sets[0]) desk.panes[0] = desk.sets[0].id;
  persist(desk);
}

export function setWatchLabels(on: boolean) {
  const desk = copyDesk(getWatchDesk());
  desk.labels = on;
  persist(desk);
}

/** Markets to sample: union of every assigned pane, including hidden layout slots. */
export function samplingSymbols(desk: WatchDesk): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const id of desk.panes) {
    if (!id) continue;
    const set = desk.sets.find((s) => s.id === id);
    if (!set) continue;
    for (const symbol of set.symbols) {
      if (seen.has(symbol)) continue;
      seen.add(symbol);
      out.push(symbol);
    }
  }
  return out;
}

function subscribeWatchDesk(onChange: () => void) {
  const handler = () => {
    cache = null;
    onChange();
  };
  try {
    window.addEventListener(EVENT, handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener(EVENT, handler);
      window.removeEventListener("storage", handler);
    };
  } catch {
    return () => {};
  }
}

export function useWatchDesk() {
  return useSyncExternalStore(subscribeWatchDesk, getWatchDesk, getWatchDesk);
}
