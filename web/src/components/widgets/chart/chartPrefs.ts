import type { ScanTab } from "@/components/widgets/ScanBoard";

export const VOL_KEY = "mayedge-chart-vol";
export const OI_KEY = "mayedge-chart-oi";
export const FUND_KEY = "mayedge-chart-fund";
export const BBO_KEY = "mayedge-chart-bbo";
export const MAYREKT_KEY = "mayedge-chart-mayrekt";
export const MODE_KEY = "mayedge-chart-mode";
export const SCAN_TAB_KEY = "mayedge-scan-tab";
export const RIGHT_OFFSET = 8;

export const CHART_MODES = ["price", "scan", "watch"] as const;
export type ChartMode = (typeof CHART_MODES)[number];
export const SCAN_TABS = ["rel", "liqs", "act", "tones"] as const;

export function loadVol(): boolean {
  try {
    return localStorage.getItem(VOL_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadOi(): boolean {
  try {
    return localStorage.getItem(OI_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadFund(): boolean {
  try {
    return localStorage.getItem(FUND_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadBbo(): boolean {
  try {
    return localStorage.getItem(BBO_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadMayRekt(): boolean {
  try {
    return localStorage.getItem(MAYREKT_KEY) === "1";
  } catch {
    return false;
  }
}

export function loadMode(): ChartMode {
  try {
    const raw = localStorage.getItem(MODE_KEY);
    if (raw === "rs" || raw === "scan") {
      if (raw === "rs") {
        try {
          localStorage.setItem(MODE_KEY, "scan");
        } catch {
          /* ignore */
        }
      }
      return "scan";
    }
    if (raw === "price") return "price";
    if (raw === "watch") return "watch";
  } catch {
    /* ignore */
  }
  return "price";
}

export function loadScanTab(): ScanTab {
  try {
    const raw = localStorage.getItem(SCAN_TAB_KEY);
    if ((SCAN_TABS as readonly string[]).includes(raw ?? "")) return raw as ScanTab;
  } catch {
    /* ignore */
  }
  return "rel";
}
