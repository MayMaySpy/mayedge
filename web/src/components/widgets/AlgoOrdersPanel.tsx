import { useState } from "react";
import { notifyErr, notifyOk } from "@/lib/notify";
import { PanelHeader } from "@/components/desk/PanelHeader";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { AlgoRow } from "@/components/widgets/algo/AlgoRow";
import { algoBlotter } from "@/lib/algos";
import { api, type AlgoState } from "@/lib/api";
import { setAlgo, useLiveAlgos } from "@/lib/liveData";

interface AlgoOrdersPanelProps {
  symbol?: string | null;
  tradingEnabled: boolean;
  onClose?: () => void;
}

function AlgoList({
  rows,
  empty,
  symbol,
  tradingEnabled,
  busyId,
  showControls,
  onStop,
  onPause,
  onResume,
}: {
  rows: AlgoState[];
  empty: string;
  symbol?: string | null;
  tradingEnabled: boolean;
  busyId: string | null;
  showControls: boolean;
  onStop: (algoId: string) => void;
  onPause: (algoId: string) => void;
  onResume: (algoId: string) => void;
}) {
  if (rows.length === 0) {
    return (
      <Empty className="rounded-none border-0 p-4">
        <EmptyDescription className="text-[11px] text-muted">{empty}</EmptyDescription>
      </Empty>
    );
  }

  return (
    <>
      {rows.map((algo) => (
        <AlgoRow
          key={algo.algo_id ?? `${algo.symbol}-${algo.created_at}`}
          algo={algo}
          busy={busyId === algo.algo_id || busyId === "*"}
          emphasize={!!symbol && algo.symbol === symbol}
          tradingEnabled={tradingEnabled}
          onStop={
            showControls && algo.algo_id ? () => onStop(algo.algo_id!) : undefined
          }
          onPause={
            showControls && algo.algo_id ? () => onPause(algo.algo_id!) : undefined
          }
          onResume={
            showControls && algo.algo_id ? () => onResume(algo.algo_id!) : undefined
          }
        />
      ))}
    </>
  );
}

export function AlgoOrdersPanel({ symbol, tradingEnabled, onClose }: AlgoOrdersPanelProps) {
  const book = useLiveAlgos();
  const { working, history } = algoBlotter(book);
  const [tab, setTab] = useState<"working" | "history">("working");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [scope, setScope] = useState<"all" | "pair">("all");

  const filterSym = scope === "pair" && symbol ? symbol : null;
  const workingRows = filterSym ? working.filter((a) => a.symbol === filterSym) : working;
  const historyRows = filterSym ? history.filter((a) => a.symbol === filterSym) : history;

  const stopOne = async (algoId: string) => {
    if (!tradingEnabled || busyId) return;
    setBusyId(algoId);
    try {
      const book = await api.chaseStop(algoId);
      setAlgo(book);
      const still = (book.working ?? []).find((a) => a.algo_id === algoId);
      if (still?.status === "error") {
        notifyErr(still.error || `${algoId} stop incomplete`);
      } else {
        notifyOk(`${algoId} stopped`);
      }
    } catch (err) {
      notifyErr(err instanceof Error ? err.message : "Stop failed");
    } finally {
      setBusyId(null);
    }
  };

  const pauseOne = async (algoId: string) => {
    if (!tradingEnabled || busyId) return;
    setBusyId(algoId);
    try {
      const book = await api.chasePause(algoId);
      setAlgo(book);
      notifyOk(`${algoId} paused`);
    } catch (err) {
      notifyErr(err instanceof Error ? err.message : "Pause failed");
    } finally {
      setBusyId(null);
    }
  };

  const resumeOne = async (algoId: string) => {
    if (!tradingEnabled || busyId) return;
    setBusyId(algoId);
    try {
      const book = await api.chaseUnpause(algoId);
      setAlgo(book);
      notifyOk(`${algoId} resumed`);
    } catch (err) {
      notifyErr(err instanceof Error ? err.message : "Resume failed");
    } finally {
      setBusyId(null);
    }
  };

  const stopAll = async () => {
    if (!tradingEnabled || busyId || working.length === 0) return;
    setBusyId("*");
    try {
      await api.chaseStop(undefined);
      setAlgo(await api.algoStatus());
      notifyOk("All algos stopped");
    } catch (err) {
      notifyErr(err instanceof Error ? err.message : "Stop failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader
        title="Algos"
        onClose={onClose}
        trailing={
          tradingEnabled && working.length > 0 ? (
            <Button
              variant="danger"
              size="sm"
              disabled={!!busyId}
              onClick={() => void stopAll()}
              className="h-6"
            >
              Stop all
            </Button>
          ) : null
        }
      >
        <span className="font-mono text-[10px] tabular-nums text-text">{working.length}</span>
      </PanelHeader>

      <Tabs
        value={tab}
        onValueChange={(v) => {
          if (v === "working" || v === "history") setTab(v);
        }}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div className="flex h-7 shrink-0 items-center gap-1 border-b border-rule px-1.5">
          <TabsList className="h-7 border-0">
            <TabsTrigger value="working" className="h-7">
              Working
            </TabsTrigger>
            <TabsTrigger value="history" className="h-7">
              History
            </TabsTrigger>
          </TabsList>
          <ToggleGroup
            type="single"
            variant="seg"
            size="sm"
            spacing={0}
            value={scope}
            onValueChange={(v) => {
              if (v === "all" || v === "pair") setScope(v);
            }}
            className="ml-auto"
          >
            <ToggleGroupItem value="all">All</ToggleGroupItem>
            <ToggleGroupItem value="pair" disabled={!symbol}>
              {symbol ?? "Pair"}
            </ToggleGroupItem>
          </ToggleGroup>
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <TabsContent value="working" className="mt-0">
            <AlgoList
              rows={workingRows}
              empty="No working algos. Place one from the ticket."
              symbol={symbol}
              tradingEnabled={tradingEnabled}
              busyId={busyId}
              showControls
              onStop={(id) => void stopOne(id)}
              onPause={(id) => void pauseOne(id)}
              onResume={(id) => void resumeOne(id)}
            />
          </TabsContent>
          <TabsContent value="history" className="mt-0">
            <AlgoList
              rows={historyRows}
              empty="No past algos yet."
              symbol={symbol}
              tradingEnabled={tradingEnabled}
              busyId={busyId}
              showControls={false}
              onStop={() => {}}
              onPause={() => {}}
              onResume={() => {}}
            />
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </div>
  );
}
