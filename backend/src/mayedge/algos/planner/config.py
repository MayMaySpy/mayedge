PLANNER_COI_BASE = 11_000_000_000
PLANNER_COI_END = 12_000_000_000

MAX_TARGETS = 5
MAX_SLIPPAGE = 0.05
DEFAULT_SLIPPAGE = 0.01

# EL4: the venue's resting-order limit on one Market (Standard, docs/lighter-limits.md).
MARKET_ORDER_CAP = 30
# EL4: algo sends a Ladder entry leaves free for the stop when it rests its rungs.
RUNG_TX_RESERVE = 3

# Amends a minute, shared by the Planners on one Market; the same budget as Trail F7.
MARKET_AMENDS_PER_MIN = 15

RATE_LIMIT_COOLDOWN_MS = 2_000
MIN_PLACE_GAP_MS = 100

# An order the account feed has not shown after this was refused.
ACK_GRACE_MS = 10_000
# A Market entry the feed never shows is over after this.
MARKET_ENTRY_GRACE_MS = 10_000
# A Clip gone from the book, or a flat Position, is believed after this.
MISSING_GRACE_MS = 3_000
# M6: the Position must disagree for this long before Planner pauses.
MISMATCH_GRACE_MS = 3_000
CANCEL_WAIT_TRIES = 10
CANCEL_WAIT_S = 0.2
