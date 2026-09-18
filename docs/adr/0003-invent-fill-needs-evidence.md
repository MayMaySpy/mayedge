# Invent-fill needs evidence

When a Chase Clip vanishes from the open-order cache, the ledger does not treat silence as a fill. Invent-fill is allowed only when trade or open-sync evidence already credits that Clip. Without evidence, the row is cancelled and Chase auto-rests after a retry delay.

A vanish can be a cancel, a lag, or a fill the trade tape has not shown yet. Crediting the full Clip from silence would fake a fill and shrink remaining size. Waiting forever would leave the job stuck with a ghost child.
