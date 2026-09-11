"""Timing and COI constants for chase-grid."""

from __future__ import annotations

GRID_COI_BASE = 10_000_000_000
GRID_COI_END = 11_000_000_000
HISTORY_CAP = 30

# Two live chase clips — stagger requotes vs single chase.
MIN_REQUOTE_MS = 2_000
MIN_PLACE_GAP_MS = 100
ACK_WAIT_MS = 4_000
STALE_ACK_MS = 8_000
RATE_LIMIT_COOLDOWN_MS = 20_000
NONCE_COOLDOWN_MS = 3_000
STOP_CANCEL_TRIES = 3
STOP_CANCEL_GAP_S = 0.2
MISSING_FILL_GRACE_MS = 800
UNPROVEN_RETRY_MS = 2_000
RESTORE_FEED_TIMEOUT_S = 30.0
REST_TRADES_PAGE_LIMIT = 100
REST_TRADES_MAX_PAGES = 20

MAX_UNMATCHED_TPS = 3  # merge when a 4th would appear
DEFAULT_BE_BPS = 0  # live maker+taker from accountLimits; Standard is 0
DEFAULT_REENTRY_COOLDOWN_MS = 30_000
DEFAULT_REENTRY_BPS = 4
DEFAULT_POST_BE_COOLDOWN_MS = 60_000

AUTO_RESUME_ERRORS = frozenset({"unproven_missing_clip", "trades_reconcile_failed"})
