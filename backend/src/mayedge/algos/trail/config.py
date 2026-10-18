TRAIL_COI_BASE = 12_000_000_000
TRAIL_COI_END = 13_000_000_000

# F6: a venue order moves by at least this share of the distance, and at least STEP_MIN_TICKS.
STEP_SHARE = "0.1"
STEP_MIN_TICKS = 2
MIN_GAP_MS = 5_000
# F7: Amends a minute, shared by every Trail on one Market.
MARKET_AMENDS_PER_MIN = 15
# S3: the smallest distance, in ticks.
MIN_DISTANCE_TICKS = 2
# S2: how many of each kind may run on one Market.
MAX_PER_MARKET = {"entry": 1, "stop": 1, "tp": 3}

MAX_SLIPPAGE = 0.05
DEFAULT_SLIPPAGE = 0.01

RATE_LIMIT_COOLDOWN_MS = 2_000
# An order the account feed has not shown after this was refused.
ACK_GRACE_MS = 10_000
# A Market order the feed never shows is over after this.
MARKET_GRACE_MS = 10_000
# A Clip gone from the book, or a flat Position, is believed after this.
MISSING_GRACE_MS = 3_000
CANCEL_WAIT_TRIES = 10
CANCEL_WAIT_S = 0.2
