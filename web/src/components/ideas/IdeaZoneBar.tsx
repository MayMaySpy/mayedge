import { useEffect, useRef, useState } from "react";
import type { Idea } from "@/lib/api.gen";
import { price } from "@/lib/journalFormat";
import { zoneBarMarks, type ZoneMark } from "@/lib/ideas";

const HEIGHT = 56;

function color(kind: ZoneMark["kind"], side: Idea["side"]): string {
  if (kind === "stop") return "var(--color-ask)";
  if (kind === "target") return "var(--color-bid)";
  if (kind === "zone") return side === "short" ? "var(--color-ask)" : "var(--color-bid)";
  return "var(--color-foreground)";
}

/** The price ruler. Geometry comes from `zoneBarMarks`; this only draws it. */
export function IdeaZoneBar({
  idea,
  last,
  onEditPlan,
}: {
  idea: Idea;
  last: number | null;
  onEditPlan: () => void;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(560);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const apply = () => setWidth(Math.max(1, el.clientWidth || 560));
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const bar = zoneBarMarks(idea, last, width);
  if (!bar) {
    return (
      <button type="button" className="text-left text-muted-foreground" onClick={onEditPlan}>
        No Plan yet. Add an entry and a stop.
      </button>
    );
  }
  const labeled = labelsThatFit(bar.marks);
  const zoneColor = idea.side === "short" ? "var(--color-ask)" : "var(--color-bid)";
  return (
    <svg ref={ref} width="100%" height={HEIGHT} className="block overflow-visible font-mono" role="img" aria-label="Plan">
      {bar.zone ? (
        <rect
          x={Math.min(bar.zone.x0, bar.zone.x1)}
          y={16}
          width={Math.max(2, Math.abs(bar.zone.x1 - bar.zone.x0))}
          height={8}
          fill={zoneColor}
          opacity={0.25}
        />
      ) : null}
      {bar.marks.map((mark) => {
        const text = labeled.has(mark);
        const x = Math.min(width - 36, Math.max(36, mark.x));
        const shown = mark.kind === "last" ? price(mark.price) : mark.price;
        return (
          <g key={`${mark.kind}-${mark.label}-${mark.price}`}>
            {mark.kind === "last" ? (
              <path d={`M ${mark.x} 14 l 4 6 l -8 0 z`} fill={color(mark.kind, idea.side)} />
            ) : (
              <line x1={mark.x} x2={mark.x} y1={12} y2={28} stroke={color(mark.kind, idea.side)} strokeWidth={1.5} />
            )}
            {text ? (
              <text x={x} y={10} textAnchor="middle" className="fill-muted-foreground text-xs">
                {mark.label}
              </text>
            ) : null}
            {text ? (
              <text x={x} y={42} textAnchor="middle" className="fill-foreground text-xs">
                {shown}
              </text>
            ) : null}
            {text && mark.sub ? (
              <text x={x} y={54} textAnchor="middle" className="fill-muted-foreground text-xs">
                {mark.sub}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

/** Drop a label that would sit on top of one already drawn. Last gives way first. */
function labelsThatFit(marks: ZoneMark[]): Set<ZoneMark> {
  const kept: ZoneMark[] = [];
  const clash = (mark: ZoneMark) => kept.find((row) => Math.abs(row.x - mark.x) < 72);
  for (const mark of marks) {
    const hit = clash(mark);
    if (!hit) {
      kept.push(mark);
      continue;
    }
    if (hit.kind === "last" && mark.kind !== "last") {
      kept.splice(kept.indexOf(hit), 1);
      kept.push(mark);
    }
  }
  return new Set(kept);
}
