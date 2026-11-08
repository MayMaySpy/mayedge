import { useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import type { Idea } from "@/lib/api.gen";
import { afterChart } from "@/lib/startup";

const IDEAS_MS = 60_000;

let ideas: Idea[] = [];
let timer: number | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

async function load() {
  try {
    const body = await api.ideas("open");
    ideas = body.ideas;
    emit();
  } catch {
    /* The desk still runs if Ideas are unreachable. */
  }
}

function ensure() {
  if (timer != null) return;
  afterChart(() => void load());
  timer = window.setInterval(() => {
    if (document.visibilityState === "visible") void load();
  }, IDEAS_MS);
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  ensure();
  return () => {
    listeners.delete(onChange);
    if (listeners.size === 0 && timer != null) {
      window.clearInterval(timer);
      timer = null;
    }
  };
}

/** Open Ideas for the picker mark and the chart overlay. One poll, shared. */
export function useOpenIdeas(): Idea[] {
  return useSyncExternalStore(subscribe, () => ideas, () => []);
}
