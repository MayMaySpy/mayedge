"""Timing and COI constants for the Massager."""

from __future__ import annotations

from mayedge.algos.common import in_coi_range

MASSAGER_COI_BASE = 13_000_000_000
MASSAGER_COI_END = 14_000_000_000


def is_massager_client_order(coi: int | None) -> bool:
    return in_coi_range(coi, MASSAGER_COI_BASE, MASSAGER_COI_END)


# MS15: a Core change counts once it has held this long, so the Massager's own fill
# seen on the Position before its order row is not taken for an outside fill.
OUTSIDE_GRACE_MS = 3_000
MIN_PLACE_GAP_MS = 100
# MS13: the catch-up follows the touch no faster than this.
MIN_REQUOTE_MS = 2_000
ACK_WAIT_MS = 4_000
