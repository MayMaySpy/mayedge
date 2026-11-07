# Massager rules

What a **Massager** does. Change a rule here first, then the code and the test that pins it, in one commit ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)). The scope it came from is [massager-scope.md](massager-scope.md).

Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here. "code" means the number is not a knob. Sizes are signed: long above zero, short below.

Last checked against the code: 2026-11-07. Phase 1: the rules below are coded as a pure planner (`algos/massager/plan.py`). Nothing places an order yet; the job, the desk wiring and the ticket are phases 2 to 4.

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
| MS9 | From level L it rests a sell at L + 1 and L + 2 and a buy at L − 1 and L − 2, one Clip each, none past ±levels. A level whose Clip fills in full becomes L. A partial fill does not move L. | 2 each side is code | `test_two_levels_rest_each_side`, `test_the_edge_rests_only_inward`, `test_a_full_fill_moves_the_level` |

## What it counts

| # | Rule | Value | Test |
|---|---|---|---|
| MS10 | **Captured** is the Lean's realized profit by average cost, less the Massager's fees. A Clip sold and bought back one Step lower captures Clip × Step less fees. A fill through zero closes what it can and opens the rest at its price. | | `test_a_round_trip_captures_one_step`, `test_a_fill_through_zero_opens_the_rest` |
| MS11 | **Basis** = Core entry − (Core's sign) × Captured ÷ Core's size. Core entry is the venue entry at start, moved by an outside add at its price by average cost. An outside reduction leaves it. | | `test_basis_takes_captured_off_the_core_entry`, `test_an_outside_add_moves_the_core_entry` |
| MS12 | Core = Position − Lean, after every fill from outside. A Position flat or on the other side of the Core's side stops the Massager. A Core no larger than the Swing pauses it. Otherwise it runs. | | `test_an_outside_close_stops_it`, `test_a_core_shrunk_to_the_swing_pauses_it`, `test_an_outside_add_keeps_it_running` |
