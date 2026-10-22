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

  const loadDetail = useCallback(async (id: string) => {
    const detail = await api.idea(id);
    upsert(detail.idea);
    if (selectedRef.current === id) setLog(detail.log);
    return detail;
  }, [upsert]);

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
        upsert(detail.idea);
        setLog(detail.log);
      })
      .catch((e: unknown) => {
        if (live && e instanceof ApiError && e.status === 404) setSelectedId(null);
      });
    return () => {
      live = false;
    };
  }, [selectedId, upsert]);

  useEffect(() => {
    const pull = () => {
      if (document.visibilityState !== "visible") return;
      void api.markets().then(setMarkets).catch(() => undefined);
    };
    const pullIdeas = () => {
      if (document.visibilityState !== "visible") return;
      void api
        .ideas("all")
        .then((body) => replace(body.ideas))
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
  }, [loadDetail, replace]);

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

  const fail = async (id: string, before: Idea | undefined, e: unknown) => {
    if (before) upsert(before);
    if (e instanceof ApiError && e.status === 409) {
      await loadDetail(id).catch(() => undefined);
      setFormEpoch((n) => n + 1);
      notifyErr(e.message);
    } else if (!(e instanceof ApiError && e.field)) {
      notifyErr(message(e, "Not saved, retry"));
    }
    throw e;
  };

  const patch = async (id: string, body: Omit<IdeaPatch, "seen_updated_at">) => {
    const before = ideasRef.current.find((row) => row.id === id);
    if (!before) throw new Error("Not saved, retry");
    upsert({ ...before, ...body, tags: body.tags ?? before.tags, catalysts: body.catalysts ?? before.catalysts, targets: body.targets ?? before.targets } as Idea);
    try {
      const saved = await api.ideaPatch(id, { ...body, seen_updated_at: before.updated_at });
      upsert(saved.idea);
      return saved.idea;
    } catch (e) {
      return fail(id, before, e);
    }
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

  const moveStatus = async (id: string, body: IdeaStatusBody) => {
    const before = ideasRef.current.find((row) => row.id === id);
    try {
      const saved = await api.ideaStatus(id, body);
      upsert(saved.idea);
      await loadDetail(id);
      return saved.idea;
    } catch (e) {
      notifyErr(message(e, "That status move is not allowed."));
      if (before) upsert(before);
      throw e;
    }
  };

  const saveReview = async (id: string, body: IdeaReviewBody) => {
    const before = ideasRef.current.find((row) => row.id === id);
    try {
      const saved = await api.ideaReview(id, body);
      upsert(saved.idea);
      return saved.idea;
    } catch (e) {
      if (before) upsert(before);
      notifyErr(message(e, "Not saved, retry"));
      throw e;
    }
  };

  const addLog = async (id: string, body: string) => {
    const saved = await api.ideaLog(id, { body });
    setLog((rows) => [saved.line, ...rows]);
    await loadDetail(id).catch(() => undefined);
    return saved.line;
  };

  const remove = async (id: string) => {
    await api.ideaDelete(id);
    replace(ideasRef.current.filter((row) => row.id !== id));
    if (selectedRef.current === id) setSelectedId(null);
  };

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
