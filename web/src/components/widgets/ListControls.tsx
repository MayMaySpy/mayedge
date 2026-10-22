import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

export type Scope = "all" | "pair";

/** All markets, or the one on the chart. */
export function ScopeToggle({
  scope,
  onScopeChange,
  pair,
  className,
}: {
  scope: Scope;
  onScopeChange: (scope: Scope) => void;
  /** The chart's market, or null when there is none to narrow to. */
  pair: string | null | undefined;
  className?: string;
}) {
  return (
    <ToggleGroup
      type="single"
      variant="seg"
      size="sm"
      spacing={0}
      value={scope}
      onValueChange={(v) => {
        if (v === "all" || v === "pair") onScopeChange(v);
      }}
      className={className}
    >
      <ToggleGroupItem value="all">All</ToggleGroupItem>
      <ToggleGroupItem value="pair" disabled={!pair}>
        {pair ?? "Pair"}
      </ToggleGroupItem>
    </ToggleGroup>
  );
}

/** Grey bars in place of rows while a list loads. */
export function LoadingRows({ rows = 4, className = "h-5" }: { rows?: number; className?: string }) {
  return (
    <div className="flex flex-col gap-1 p-2">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={`${className} animate-pulse bg-elevated`} />
      ))}
    </div>
  );
}

/** The next page of a list, shown while there is one. */
export function LoadMore({
  cursor,
  loading,
  onLoad,
}: {
  cursor: string | null;
  loading: boolean;
  onLoad: () => void;
}) {
  if (!cursor) return null;
  return (
    <div className="flex justify-center pt-2 pb-3">
      <Button variant="outline" size="sm" disabled={loading} onClick={onLoad}>
        {loading ? "Loading…" : "Load more"}
      </Button>
    </div>
  );
}
