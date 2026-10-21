/** What the desk has already said about Auto kill on this page. */
export interface AutoKillNoticeSeen {
  seeded: boolean;
  firedAt: number | null;
  failed: boolean;
}

export const AUTO_KILL_NOTICE_UNSEEN: AutoKillNoticeSeen = {
  seeded: false,
  firedAt: null,
  failed: false,
};

/**
 * One toast per fire, plus one more if it could not flatten. The first `auto_kill` message a
 * page gets only seeds: the server resends the last fire on every connect, and the Auto kill
 * section's "Last fired" line already shows it.
 */
export function autoKillNotice(
  seen: AutoKillNoticeSeen,
  firedAt: number | null,
  status: string | null
): { seen: AutoKillNoticeSeen; notice: "fired" | "partial" | null } {
  const partial = status === "partial";
  if (!seen.seeded) {
    return { seen: { seeded: true, firedAt, failed: partial }, notice: null };
  }
  if (firedAt == null) return { seen, notice: null };
  if (firedAt !== seen.firedAt) {
    return { seen: { seeded: true, firedAt, failed: partial }, notice: partial ? "partial" : "fired" };
  }
  if (partial && !seen.failed) {
    return { seen: { ...seen, failed: true }, notice: "partial" };
  }
  return { seen, notice: null };
}
