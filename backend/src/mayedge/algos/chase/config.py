"""Timing and COI constants shared by chase runner modules."""

from __future__ import annotations

CHASE_COI_BASE = 8_000_000_000
CHASE_COI_END = 9_000_000_000
HISTORY_CAP = 30
# Lighter L1 address cap is 40 txs / 60s. Stay under so user txs still fit.
MIN_REQUOTE_MS = 2_000
ACK_WAIT_MS = 4_000
STALE_ACK_MS = 8_000
RATE_LIMIT_COOLDOWN_MS = 20_000
NONCE_COOLDOWN_MS = 3_000
# Stop/pause: retry venue cancel; WS cache often lags a successful pull.
STOP_CANCEL_TRIES = 3
STOP_CANCEL_GAP_S = 0.2
# Wait for trades / cache catch-up before treating a vanished child as missing.
MISSING_FILL_GRACE_MS = 800
# After REST says the child is gone with no fill, wait then credit again and rest.
UNPROVEN_RETRY_MS = 2_000
# Hydrated ERROR jobs that should continue quoting without an operator click.
AUTO_RESUME_ERRORS = frozenset({"unproven_missing_clip", "trades_reconcile_failed"})
# Restore: wait for book + account before requoting after process start.
RESTORE_FEED_TIMEOUT_S = 30.0
# Rearm trade credit: paginate REST trades (fail closed if cap hit).
REST_TRADES_PAGE_LIMIT = 100
REST_TRADES_MAX_PAGES = 20
