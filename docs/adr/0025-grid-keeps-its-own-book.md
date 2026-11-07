# Grid keeps its own book

Supersedes [ADR 0002](0002-grid-is-exclusive-on-a-market.md).

A Grid counts only what its own Clips filled. It starts flat whatever Position is open, it no longer snaps its inventory to the Position, and its take-profits and break-even flatten are plain orders sized to its own lots, not reduce-only. With that, Grid runs beside Chase, Ladder and TWAP on one Market. It still refuses beside a Planner, which owns the exit ([ADR 0015](0015-planner-owns-the-exit.md)), and beside a Trail. Rules are in [grid-rules.md](../grid-rules.md).

A ranging Market wants two jobs at once: accumulate low with a Ladder and play the range with a Grid. ADR 0002 forbade it because Grid took the whole Position as its inventory, so its take-profits would sell what the Ladder bought. Giving Grid its own book removes that collision instead of forbidding the pair.

Reduce-only could not stay. On one account the Position is net, so a Grid short beside a Ladder long sells into the long, and its buy-back is an add the venue refuses as reduce-only. The cost is that a Grid take-profit can open a Position when the Market was closed by something else. Grid does not guess at that from the net Position; the operator stops it, and Kill halts it.
