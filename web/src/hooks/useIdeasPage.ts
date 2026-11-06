import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ApiError, api, type Market } from "@/lib/api";
import type { Idea, IdeaBody, IdeaLogLine, IdeaPatch, IdeaReviewBody, IdeaStatusBody } from "@/lib/api.gen";
import {
  countByStatus,
  defaultIdeaSort,
  ideaMatches,
  readIdeasLocation,
  sortIdeas,
  statusOf,
  type IdeaSort,
  type IdeaStatusFilter,
} from "@/lib/ideas";
import { notifyErr } from "@/lib/notify";

const MARKETS_MS = 10_000;

function withPatch(idea: Idea, body: Omit<IdeaPatch, "seen_updated_at">): Idea {
  return {
    ...idea,
    ...body,
    tags: body.tags ?? idea.tags,
    catalysts: body.catalysts ?? idea.catalysts,
    targets: body.targets ?? idea.targets,
  } as Idea;
}
const IDEAS_MS = 60_000;

export type IdeaSeed = { symbol: string; entry: string; stop: string; targets: string[] };

function message(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/** Ideas, markets, and the URL. Markets every 10s, Ideas every 60s, both only while the tab is visible. */
export function useIdeasPage() {
  const [query] = useState(readIdeasLocation);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [markets, setMarkets] = useState<Market[]>([]);
  const [log, setLog] = useState<IdeaLogLine[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(query.id);
  const [status, setStatusState] = useState<IdeaStatusFilter>(query.status);
  const [sort, setSort] = useState<IdeaSort>(query.sort);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [seed, setSeed] = useState<IdeaSeed | null>(null);
  const [formEpoch, setFormEpoch] = useState(0);
  const ideasRef = useRef(ideas);
  const selectedRef = useRef(selectedId);
  useEffect(() => {
    ideasRef.current = ideas;
  }, [ideas]);
  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);

  const replace = useCallback((next: Idea[]) => {
    ideasRef.current = next;
    setIdeas(next);
  }, []);

  const upsert = useCallback((idea: Idea) => {
    const rows = ideasRef.current;
    const known = rows.some((row) => row.id === idea.id);
    replace(known ? rows.map((row) => (row.id === idea.id ? idea : row)) : [idea, ...rows]);
  }, [replace]);

  // Edits sent but not answered yet. A server answer is shown with them on top, so a field
  // typed after it does not flicker back to its old value.
  const pending = useRef(new Map<string, Omit<IdeaPatch, "seen_updated_at">[]>());
  const shown = useCallback((idea: Idea) => {
    let row = idea;
    for (const body of pending.current.get(idea.id) ?? []) row = withPatch(row, body);
    return row;
  }, []);
  const settle = useCallback((idea: Idea) => upsert(shown(idea)), [shown, upsert]);
  const forget = (id: string, body: Omit<IdeaPatch, "seen_updated_at">) => {
    const rows = (pending.current.get(id) ?? []).filter((row) => row !== body);
    if (rows.length) pending.current.set(id, rows);
    else pending.current.delete(id);
  };

  const loadDetail = useCallback(async (id: string) => {
    const detail = await api.idea(id);
    settle(detail.idea);
    if (selectedRef.current === id) setLog(detail.log);
    return detail;
  }, [settle]);

  useEffect(() => {
    let live = true;
    Promise.all([api.ideas("all"), api.markets()])
      .then(([body, listed]) => {
        if (!live) return;
        replace(body.ideas);
        setMarkets(listed);
      })
      .catch((e: unknown) => {
        if (live) notifyErr(message(e, "Failed to load Ideas"));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [replace]);

  useEffect(() => {
    if (loading) return;
    if (!query.symbol || query.id) return;
    const seeded = Boolean(query.entry || query.stop || query.targets.length);
    if (seeded) {
      setSeed({ symbol: query.symbol, entry: query.entry ?? "", stop: query.stop ?? "", targets: query.targets });
      setCreating(true);
      return;
    }
    const hit = ideasRef.current.find(
      (idea) => idea.symbol === query.symbol && (idea.status === "watching" || idea.status === "active"),
    );
    if (hit) setSelectedId(hit.id);
    else {
      setSeed({ symbol: query.symbol, entry: "", stop: "", targets: [] });
      setCreating(true);
    }
  }, [loading, query]);

  useEffect(() => {
    if (!selectedId) {
      setLog([]);
      return;
    }
    let live = true;
    api
      .idea(selectedId)
      .then((detail) => {
        if (!live) return;
        settle(detail.idea);
        setLog(detail.log);
      })
      .catch((e: unknown) => {
        if (live && e instanceof ApiError && e.status === 404) setSelectedId(null);
      });
    return () => {
      live = false;
    };
  }, [selectedId, settle]);

  useEffect(() => {
    const pull = () => {
      if (document.visibilityState !== "visible") return;
      void api.markets().then(setMarkets).catch(() => undefined);
    };
    const pullIdeas = () => {
      if (document.visibilityState !== "visible") return;
      void api
        .ideas("all")
        .then((body) => replace(body.ideas.map(shown)))
        .catch(() => undefined);
      const id = selectedRef.current;
      if (id) void loadDetail(id).catch(() => undefined);
    };
    const marketsTimer = window.setInterval(pull, MARKETS_MS);
    const ideasTimer = window.setInterval(pullIdeas, IDEAS_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        pull();
        pullIdeas();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(marketsTimer);
      window.clearInterval(ideasTimer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [loadDetail, replace, shown]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (selectedId) params.set("id", selectedId);
    if (status !== "open") params.set("status", status);
    if (sort !== defaultIdeaSort(status)) params.set("sort", sort);
    const qs = params.toString();
    const next = qs ? `/ideas?${qs}` : "/ideas";
    const current = `${window.location.pathname}${window.location.search}`;
    if (current !== next) window.history.replaceState(null, "", next);
    const idea = ideas.find((row) => row.id === selectedId);
    document.title = idea ? `${idea.symbol} ${idea.side} · Ideas` : "Ideas";
  }, [ideas, selectedId, sort, status]);

  const marketMap = useMemo(() => new Map(markets.map((market) => [market.symbol, market])), [markets]);
  const visible = useMemo(
    () => sortIdeas(ideas.filter((idea) => statusOf(status, idea) && ideaMatches(idea, search)), marketMap, sort),
    [ideas, marketMap, search, sort, status],
  );
  const counts = useMemo(() => countByStatus(ideas), [ideas]);
  const selected = ideas.find((idea) => idea.id === selectedId) ?? null;

  const setStatus = (next: IdeaStatusFilter) => {
    setStatusState(next);
    if (sort === defaultIdeaSort(status)) setSort(defaultIdeaSort(next));
  };

  // One write per Idea at a time: each patch sends the updated_at of the answer before it,
  // so the page's own quick edits never refuse each other (docs/idea-rules.md, the patch rule).
  const queues = useRef(new Map<string, Promise<unknown>>());
  const queued = useCallback(<T,>(id: string, work: () => Promise<T>): Promise<T> => {
    const next = (queues.current.get(id) ?? Promise.resolve()).then(work, work);
    const tail = next.catch(() => undefined);
    queues.current.set(id, tail);
    void tail.then(() => {
      if (queues.current.get(id) === tail) queues.current.delete(id);
    });
    return next;
  }, []);

  const patch = (id: string, body: Omit<IdeaPatch, "seen_updated_at">) => {
    const current = ideasRef.current.find((row) => row.id === id);
    if (!current) return Promise.reject(new Error("Not saved, retry"));
    upsert(withPatch(current, body));
    pending.current.set(id, [...(pending.current.get(id) ?? []), body]);
    return queued(id, async () => {
      const seen = ideasRef.current.find((row) => row.id === id)?.updated_at ?? current.updated_at;
      try {
        const saved = await api.ideaPatch(id, { ...body, seen_updated_at: seen });
        forget(id, body);
        settle(saved.idea);
        return saved.idea;
      } catch (e) {
        forget(id, body);
        // The desk's copy wins: a refused edit drops out of the row.
        await loadDetail(id).catch(() => undefined);
        if (e instanceof ApiError && e.status === 409) {
          setFormEpoch((n) => n + 1);
          notifyErr(e.message);
        } else if (!(e instanceof ApiError && e.field)) {
          notifyErr(message(e, "Not saved, retry"));
        }
        throw e;
      }
    });
  };

  const create = async (body: IdeaBody) => {
    const saved = await api.ideaCreate(body);
    upsert(saved.idea);
    setSelectedId(saved.idea.id);
    setCreating(false);
    setSeed(null);
    if (saved.warning) {
      const warning = saved.warning;
      toast(warning.message, {
        action: { label: "Show", onClick: () => setSelectedId(warning.id) },
      });
    }
    return saved.idea;
  };

  const moveStatus = (id: string, body: IdeaStatusBody) =>
    queued(id, async () => {
      try {
        const saved = await api.ideaStatus(id, body);
        settle(saved.idea);
        await loadDetail(id).catch(() => undefined);
        return saved.idea;
      } catch (e) {
        notifyErr(message(e, "That status move is not allowed."));
        await loadDetail(id).catch(() => undefined);
        throw e;
      }
    });

  const saveReview = (id: string, body: IdeaReviewBody) =>
    queued(id, async () => {
      try {
        const saved = await api.ideaReview(id, body);
        settle(saved.idea);
        return saved.idea;
      } catch (e) {
        notifyErr(message(e, "Not saved, retry"));
        await loadDetail(id).catch(() => undefined);
        throw e;
      }
    });

  const addLog = (id: string, body: string) =>
    queued(id, async () => {
      const saved = await api.ideaLog(id, { body });
      setLog((rows) => [saved.line, ...rows]);
      await loadDetail(id).catch(() => undefined);
      return saved.line;
    });

  /** S6: a failed delete says why and keeps the Idea. */
  const remove = (id: string) =>
    queued(id, async () => {
      try {
        await api.ideaDelete(id);
      } catch (e) {
        notifyErr(message(e, "Not deleted, retry"), "Delete failed");
        throw e;
      }
      replace(ideasRef.current.filter((row) => row.id !== id));
      if (selectedRef.current === id) setSelectedId(null);
    });

  const openCreate = (next: IdeaSeed | null = null) => {
    setSeed(next);
    setCreating(true);
  };

  return {
    ideas,
    markets,
    marketMap,
    visible,
    counts,
    log,
    selected,
    selectedId,
    setSelectedId,
    status,
    setStatus,
    sort,
    setSort,
    search,
    setSearch,
    loading,
    creating,
    setCreating,
    seed,
    openCreate,
    formEpoch,
    create,
    patch,
    moveStatus,
    saveReview,
    addLog,
    remove,
  };
}
