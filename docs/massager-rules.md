# Massager rules

What a **Massager** does. Change a rule here first, then the code and the test that pins it, in one commit ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)). The scope it came from is [massager-scope.md](massager-scope.md).

Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here. "code" means the number is not a knob. Sizes are signed: long above zero, short below.

Last checked against the code: 2026-11-07. Built in four phases: the planner (`algos/massager/plan.py`), the job (`algos/massager/job.py`), the desk wiring, and the ticket, working row and chart (`web/src/lib/massager.ts`, `MassagerParamsSheet`, `MassagerRow`). The API is `POST /api/algos/massager/start` (body: `market_index`, `band_low`, `band_high`, `swing`, `clip`; a refusal is a 400 with its rule's message).

## Example

LIT, a 1,000 long Position at 3.36. Band 3.20–3.50, Swing 300, Clip 100, mid 3.42 at start.

- 3 levels each side (300 ÷ 100). Center 3.35, Step (3.50 − 3.20) ÷ 6 = 0.05. Levels 3.20, 3.25, 3.30, **3.35**, 3.40, 3.45, 3.50.
- Price has passed level +1 (3.40), so the catch-up sells 100. Lean −100, Position 900.
- From level +1 it rests sells at 3.45 and 3.50 and buys at 3.35 and 3.30, 100 each.
- The buy at 3.35 fills. Lean 0, Position 1,000, Captured (3.40 − 3.35) × 100 = $5. Basis 3.36 − 5 ÷ 1,000 = 3.355.
- Now at level 0 it rests sells at 3.40 and 3.45 and buys at 3.30 and 3.25.

## Start

| # | Rule | Value | Test |
|---|---|---|---|
| MS1 | It needs an open Position. The **Core** is that Position, and its sign is the Core's side for as long as it runs. | | `test_no_position_is_refused` |
| MS2 | The Band is two prices above 0, low below high. The book's mid at start must be inside it, ends included. | | `test_the_band_must_hold_the_price` |
| MS3 | **Swing** and Clip are above 0, Swing is a whole number of Clips (that number is the levels each side), and the Clip is at least the venue minimum and on its size step. | | `test_swing_must_be_whole_clips`, `test_a_clip_under_the_minimum_is_refused` |
| MS4 | The Swing is below the Core's size, so the Massager's own trades never take the Position flat or across. | | `test_a_swing_as_large_as_the_core_is_refused` |
| MS5 | Center = (low + high) ÷ 2. Step = (high − low) ÷ (2 × levels). Level k is Center + k × Step for k from −levels to +levels, rounded to the nearest tick. | | `test_levels_split_the_band_evenly` |
| MS6 | A Step must clear the round-trip maker fee at the Center plus one tick: Step ≥ Center × 2 × maker bps ÷ 10,000 + tick. | | `test_a_step_that_does_not_clear_fees_is_refused` |

## The lattice

| # | Rule | Value | Test |
|---|---|---|---|
| MS7 | It sells above the Center and buys below it, whatever the Core's side. Level k stands for a **Lean** of −k × Clip, so the Position stays between Core − Swing and Core + Swing. For a long that is smaller as price rises; for a short it is larger. | | `test_a_short_core_also_sells_above_the_center` |
| MS8 | At start it owes the Lean for the levels price has passed: k₀ is the furthest level at or behind the mid on its side of the Center, and the catch-up is −k₀ × Clip, a sell for k₀ above 0, a buy below, nothing at the Center. It goes on post-only at the touch (phase 2). | | `test_the_catch_up_owes_the_levels_passed`, `test_no_catch_up_at_the_center` |
| MS9 | From level L it rests a sell at L + 1 and L + 2 and a buy at L − 1 and L − 2, one Clip each, none past ±levels. Fills at a level add up across its Clips; once they make a whole Clip, that level becomes L and the count starts again. Until then L stays, and the level's next Clip is for what is left. No Clip takes the Lean past the Swing. | 2 each side is code | `test_two_levels_rest_each_side`, `test_the_edge_rests_only_inward`, `test_a_full_fill_moves_the_level`, `test_a_partly_filled_level_rests_what_is_left`, `test_no_order_takes_the_lean_past_the_swing`, `test_start_takes_the_core_and_rests_two_levels_each_side`, `test_a_partial_fill_keeps_the_level` |

## What it counts

| # | Rule | Value | Test |
|---|---|---|---|
| MS10 | **Captured** is the Lean's realized profit by average cost, less the Massager's fees (the account's maker fee on each fill). A Clip sold and bought back one Step lower captures Clip × Step less fees. A fill through zero closes what it can and opens the rest at its price. | | `test_a_round_trip_captures_one_step`, `test_a_fill_through_zero_opens_the_rest`, `test_a_round_trip_moves_the_level_and_captures_one_step` |
| MS11 | **Basis** = Core entry − (Core's sign) × Captured ÷ Core's size. Core entry is the venue entry at start, moved by an outside add by average cost at the mid when the Massager takes the change (MS15). An outside reduction leaves it. | | `test_basis_takes_captured_off_the_core_entry`, `test_an_outside_add_moves_the_core_entry`, `test_an_outside_add_moves_the_core_and_its_entry` |
| MS12 | Core = Position − Lean, after every fill from outside. A Position flat or on the other side of the Core's side stops the Massager. A Core no larger than the Swing pauses it. Otherwise it runs. Stopping and pausing pull its Clips. | | `test_an_outside_close_stops_it`, `test_a_core_shrunk_to_the_swing_pauses_it`, `test_an_outside_add_keeps_it_running` |

## The job

| # | Rule | Value | Test |
|---|---|---|---|
| MS13 | The catch-up is one post-only Clip at the touch: a sell at the best ask, a buy at the best bid, for what is still owed. When the touch moves it comes off and goes back on at the new one, no faster than every 2 s and not before the venue has shown it (4 s). Once what is owed is under the venue minimum, the lattice starts at the catch-up's level. | 2 s, 4 s are code | `test_the_catch_up_rests_at_the_touch_then_the_lattice_starts`, `test_the_catch_up_follows_the_touch` |
| MS14 | A level that would cross the touch is not sent until it would rest, like a Ladder rung, and a resting Clip the touch has crossed comes off. Price that runs past a level leaves the Lean behind until it comes back. | | `test_a_level_that_would_cross_waits` |
| MS15 | A change of Core counts only once it has held 3 s, so the Massager's own fill seen on the Position before its order row is not taken for an outside one. | 3 s is code | `test_its_own_fill_seen_early_is_not_an_outside_fill`, `test_an_outside_add_moves_the_core_and_its_entry` |
| MS16 | Lean, level, level fills, Captured, Core, Core entry and the catch-up are kept with the run. On restart the Clips are pulled as for every Clip algo, the Core is judged again from the Position (MS12), and the lattice goes back on. | | `test_a_run_comes_back_with_its_lean_level_and_core` |
| MS17 | Every Clip is a post-only Limit, never reduce-only, and it never sends a Market order. It never places, Amends or cancels a Stop or Take Profit Ticket. | | `test_start_takes_the_core_and_rests_two_levels_each_side` |
| MS18 | One Massager per Market. It runs beside Chase, Ladder and TWAP. It refuses beside a Planner, a Trail or a Grid, and they refuse beside it. Its Clips take client_order_index from `[13e9, 14e9)` ([ADR 0004](adr/0004-partitioned-client-order-index.md)); its runs are `MS-`, named Massager in the journal and in a push. | `[13e9, 14e9)` is code | `test_massager_refuses_beside_planner_trail_or_grid`, `test_its_band_is_an_algo_band`, `test_its_runs_are_named_massager`, `test_a_massager_run_reads_back_with_its_core_lean_and_captured` |

## On the page

| # | Rule | Value | Test |
|---|---|---|---|
| MS19 | **Order ticket → Algo → Massager.** The ticket's size is the Swing, and the size field says so; the sheet takes the Clip and the Band. It shows the Core, the Position range, the Center, the Step, the levels each side, what one round trip captures and the catch-up, worked out the way MS1–MS8 do. Start is blocked with MS1–MS5's own words, and on reduce-only. MS6 needs the account's fee and is the backend's to refuse. It is one action, not Buy or Sell. | | `web: massager.test.ts`, `web: algoPlugins.test.ts` |
| MS20 | **The working row** shows the Position and its range (Core ∓ Swing), Captured, Core, Lean, Basis against the Core's entry, the Band, Swing, Clip and level. Opened, it lists the live Clips by level and the fills. **The chart** draws the Band's ends and its Center; the resting levels are drawn as orders. | | `web: massager.test.ts` |

