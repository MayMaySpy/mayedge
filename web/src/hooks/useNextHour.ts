import { useSyncExternalStore } from "react";

const HOUR_MS = 3_600_000;

function nextHour(): number {
  const now = Date.now();
  return now - (now % HOUR_MS) + HOUR_MS;
}

function subscribe(onChange: () => void): () => void {
  let id: ReturnType<typeof setTimeout>;
  const arm = () => {
    id = setTimeout(() => {
      onChange();
      arm();
    }, nextHour() - Date.now() + 1);
  };
  arm();
  return () => clearTimeout(id);
}

/** The next top of the UTC hour (epoch ms), when funding settles. Wakes once an hour; no clock in render. */
export function useNextHour(): number {
  return useSyncExternalStore(subscribe, nextHour, nextHour);
}
