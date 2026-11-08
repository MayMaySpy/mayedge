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
# MS21: an ATR run reads ATR again this long after each candle of its timeframe closes,
# and a read that fails is tried again a minute later.
ATR_SETTLE_MS = 5_000
ATR_RETRY_MS = 60_000
ATR_READ_TIMEOUT_S = 5.0
TIMEFRAME_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def next_close_ms(now_ms: int, timeframe: str) -> int:
    """When the candle of ``timeframe`` open at ``now_ms`` closes."""
    period = TIMEFRAME_MS.get(timeframe, 3_600_000)
    return (now_ms // period + 1) * period


# MS23: the candle a close outside the Band is read on, how long after its close, and the
# retry after a failed read.
BAND_TIMEFRAME = "1h"
BAND_SETTLE_MS = 5_000
BAND_RETRY_MS = 60_000
