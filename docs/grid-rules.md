# Grid rules

What a **Grid** shares with the other desk algos on its Market. Change a rule here first, then the code and the test that pins it, in one commit ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)). Why: [ADR 0025](adr/0025-grid-keeps-its-own-book.md).

Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here.

Last checked against the code: 2026-11-07.

## Example

LIT ranges between 3.20 and 3.50. A Ladder buy rests 5 rungs from 3.30 down to 3.20 and fills 1,000 LIT. A Grid on the same Market, max inventory 300, buys 100 at 3.36 and sells it at 3.38. The Position is 1,100 long while Grid holds its 100, then 1,000 once Grid's take-profit fills. Grid never sells the Ladder's 1,000. A Ladder sell from 3.45 up to 3.50 can rest beside it and works only the Position it is given.

## Rules

| # | Rule | Test |
|---|---|---|
| G1 | One Grid per Market. It runs beside Chase, Ladder and TWAP on that Market, either way round. It refuses beside a Planner (ADR 0015), a Trail ([trail-rules.md](trail-rules.md) S1) or a Massager ([massager-rules.md](massager-rules.md) MS18), and they refuse beside it. | `test_grid_runs_beside_chase_ladder_and_twap`, `test_grid_and_planner_each_refuse_beside_another_algo`, `test_trail_refuses_beside_planner_or_grid`, `test_massager_refuses_beside_planner_trail_or_grid` |
| G2 | Grid's inventory is only what its own Clips filled. It starts at 0 whatever Position is open, and a Position moved by a Ticket, another algo or a hand close does not change it. Max inventory caps that inventory, not the Position. | `test_grid_starts_flat_beside_an_open_position`, `test_grid_inventory_ignores_the_position` |
| G3 | Grid's Clips are never reduce-only. A take-profit closes Grid's own lot at that lot's size, and the break-even flatten closes Grid's merged lot, whatever side the Position is on. | `test_grid_take_profit_is_not_reduce_only` |
| G4 | Grid does not watch the Position. Stop Grid when you close its Market by hand: a take-profit left on would open what it was meant to close. Kill and Auto kill halt it. | |
