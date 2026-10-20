import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type JournalSummaryGroup, type JournalTrip } from "@/lib/api";
import { inRange, type JournalRange } from "@/lib/journalFormat";
import { notifyErr } from "@/lib/notify";

/** The Journal's filters and data. The tab and the page share it; the page also asks for breakdowns. */
export function useJournal({ active, breakdowns = false }: { active: boolean; breakdowns?: boolean }) {
  const [range, setRange] = useState<JournalRange>("30d");
  const [market, setMarket] = useState("");
  const [algo, setAlgo] = useState("");
  const [trips, setTrips] = useState<JournalTrip[]>([]);
  const [strip, setStrip] = useState<JournalSummaryGroup | null>(null);
  const [days, setDays] = useState<JournalSummaryGroup[]>([]);
  const [byMarket, setByMarket] = useState<JournalSummaryGroup[]>([]);
  const [byAlgo, setByAlgo] = useState<JournalSummaryGroup[]>([]);
  const [nonce, setNonce] = useState(0);
  const key = `${range}|${market}|${algo}|${breakdowns}|${nonce}`;
  // The key of the last request that finished. Loading is derived, not set inside the effect.
  const [doneKey, setDoneKey] = useState<string | null>(null);
  const loading = active && doneKey !== key;

  useEffect(() => {
    if (!active) return;
    let live = true;
    const filter = { market: market || undefined, algo: algo || undefined };
    Promise.all([
      api.journalTrips({ ...filter, limit: breakdowns ? 1000 : 200 }),
      api.journalSummary({ range, group: "none", ...filter }),
      api.journalSummary({ range, group: "day", ...filter }),
      breakdowns ? api.journalSummary({ range, group: "market", ...filter }) : null,
      breakdowns ? api.journalSummary({ range, group: "algo", ...filter }) : null,
    ])
      .then(([tripPage, none, byDay, markets, algos]) => {
        if (!live) return;
        setTrips(tripPage.trips);
        setStrip(none.groups[0] ?? null);
        setDays(byDay.groups);
        setByMarket(markets?.groups ?? []);
        setByAlgo(algos?.groups ?? []);
      })
      .catch((e: unknown) => {
        if (live) notifyErr(e instanceof Error ? e.message : "Failed to load the journal");
      })
      .finally(() => {
        if (live) setDoneKey(key);
      });
    return () => {
      live = false;
    };
    // `key` covers every input above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, key]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const shown = useMemo(() => trips.filter((trip) => inRange(trip, range)), [range, trips]);
  const bars = useMemo(
    () =>
      [...days]
        .sort((a, b) => a.key.localeCompare(b.key))
        .map((day) => ({
          time: Math.floor(Date.parse(`${day.key}T00:00:00Z`) / 1000),
          net: Number(day.net ?? "0"),
        })),
    [days],
  );

  const saveNote = useCallback(async (trip: JournalTrip, note: string) => {
    if (note === trip.note) return;
    try {
      await api.journalNote(trip.trip_key, { note, tags: trip.tags });
      setTrips((prev) => prev.map((row) => (row.trip_key === trip.trip_key ? { ...row, note } : row)));
    } catch (e) {
      notifyErr(e instanceof Error ? e.message : "Failed to save the note");
    }
  }, []);

  return {
    range,
    setRange,
    market,
    setMarket,
    algo,
    setAlgo,
    shown,
    strip,
    bars,
    byMarket,
    byAlgo,
    loading,
    saveNote,
    reload,
  };
}

export type JournalState = ReturnType<typeof useJournal>;
