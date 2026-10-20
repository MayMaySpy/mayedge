import { useEffect, useState } from "react";

import { api, type PlannerPreview } from "@/lib/api";

/** D4. Same wait as the Planner dialog. */
export const DRAFT_PREVIEW_MS = 250;

/** Debounced planner preview. A null body draws nothing and starts nothing. */
export function useDraftPreview(body: Record<string, unknown> | null): PlannerPreview | null {
  const key = body == null ? "" : JSON.stringify(body);
  const [drawn, setDrawn] = useState<{ key: string; preview: PlannerPreview | null } | null>(null);

  useEffect(() => {
    if (!key) return;
    let live = true;
    const timer = setTimeout(() => {
      void api.plannerPreview(JSON.parse(key) as Record<string, unknown>).then(
        (preview) => {
          if (live) setDrawn({ key, preview });
        },
        () => {
          if (live) setDrawn({ key, preview: null });
        },
      );
    }, DRAFT_PREVIEW_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [key]);

  if (!key) return null;
  return drawn?.key === key ? drawn.preview : null;
}
