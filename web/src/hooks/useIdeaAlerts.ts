import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { IdeaAlert } from "@/lib/api.gen";

const REFRESH_MS = 15_000;

/** Price alerts of one Idea, refreshed while the tab is visible. Fires happen on the desk. */
export function useIdeaAlerts(ideaId: string) {
  const [held, setHeld] = useState<{ ideaId: string; alerts: IdeaAlert[] }>({ ideaId, alerts: [] });

  const reload = useCallback(async () => {
    const body = await api.ideaAlerts(ideaId);
    setHeld({ ideaId, alerts: body.alerts });
  }, [ideaId]);

  useEffect(() => {
    let live = true;
    const pull = () => {
      if (document.visibilityState !== "visible") return;
      api
        .ideaAlerts(ideaId)
        .then((body) => {
          if (live) setHeld({ ideaId, alerts: body.alerts });
        })
        .catch(() => undefined);
    };
    pull();
    const id = window.setInterval(pull, REFRESH_MS);
    return () => {
      live = false;
      window.clearInterval(id);
    };
  }, [ideaId]);

  // Another Idea's alerts never show while this one's load.
  return { alerts: held.ideaId === ideaId ? held.alerts : [], reload };
}
