from __future__ import annotations

import threading

from mayedge import db as store

MANUAL_COI_BASE = 1_000_000_000
MANUAL_COI_END = 8_000_000_000

_lock = threading.Lock()
_seq = 0
_loaded = False


def init_manual_coi_seq() -> None:
    """Load persisted manual COI counter (call once at process start)."""
    global _seq, _loaded
    with _lock:
        _seq = store.load_manual_coi_seq()
        _loaded = True


def next_manual_client_order_index() -> int:
    """Allocate client_order_index for manual (non-algo) orders."""
    global _seq
    with _lock:
        if not _loaded:
            _seq = store.load_manual_coi_seq()
        _seq += 1
        span = MANUAL_COI_END - MANUAL_COI_BASE
        coi = MANUAL_COI_BASE + (_seq % span)
        store.save_manual_coi_seq(_seq)
        return coi
