# Massager rules

What a **Massager** does. Change a rule here first, then the code and the test that pins it, in one commit ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)). The scope it came from is [massager-scope.md](massager-scope.md).

Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here. "code" means the number is not a knob. Sizes are signed: long above zero, short below.

Last checked against the code: 2026-11-08. Built in four phases: the planner (`algos/massager/plan.py`), the job (`algos/massager/job.py`), the desk wiring, and the ticket, working row and chart (`web/src/lib/massager.ts`, `MassagerParamsSheet`, `MassagerRow`). The API is `POST /api/algos/massager/start` (body: `market_index`, `band_low`, `band_high`, `swing`, and `step` for a Fixed Step or `step_mode: "atr"`, `atr_mult` and `atr_tf` for an ATR one, with optional `fresh` (MS22) and `chop` (MS24); a refusal is a 400 with its rule's message). `GET /api/algos/massager/carry?market_index=` says which Tally a Start would carry.

## Example

LIT, a 1,000 long Position at 3.36. Band 3.20–3.50, Swing 300, Step 0.05, mid 3.42 at start.

- Center 3.35, half the Band 0.15, so 3 levels each side (0.15 ÷ 0.05) and a Clip of 100 (300 ÷ 3). Levels 3.20, 3.25, 3.30, **3.35**, 3.40, 3.45, 3.50.
- Price has passed level +1 (3.40), so the catch-up sells 100. Lean −100, Position 900.
- From level +1 it rests sells at 3.45 and 3.50 and buys at 3.35 and 3.30, 100 each.
- The buy at 3.35 fills. Lean 0, Position 1,000, Captured (3.40 − 3.35) × 100 = $5. Basis (3,360 − 340 + 335) ÷ 1,000 = 3.355.
- Now at level 0 it rests sells at 3.40 and 3.45 and buys at 3.30 and 3.25.
- A 1h candle closes at 3.52, above the Band, with the Lean at −300: it pauses and pushes (MS23). The Position is 700 and its cost 2,320 (3,355 less the three sells at 3.40, 3.45 and 3.50), so Basis is 3.314.
- The trader stops it and starts a new run with a Band of 3.45–3.75. Its Core is 700 and it carries the Tally: Basis, both runs' Captured, 2 runs (MS22).

## Start

| # | Rule | Value | Test |
|---|---|---|---|
| MS1 | It needs an open Position. The **Core** is that Position, and its sign is the Core's side for as long as it runs. | | `test_no_position_is_refused` |
| MS2 | The Band is two prices above 0, low below high. The book's mid at start must be inside it, ends included. | | `test_the_band_must_hold_the_price` |
| MS3 | **Swing** and Step are above 0; the Step is how far apart the levels are. A Fixed Step is typed. An ATR Step is k × ATR(14) on the closed candles of 15m, 1h or 4h, read at start (no ATR, no start). Levels each side = half the Band ÷ Step, rounded down, and at least 1. The Clip is Swing ÷ levels, rounded down to the Market's size step, and at least the venue minimum. The run's Swing is levels × Clip, which can be a little under the Swing asked for. The Clip and the levels are fixed for the run. | | `test_the_step_sets_the_levels_and_the_clip`, `test_a_step_wider_than_half_the_band_is_refused`, `test_a_clip_under_the_minimum_is_refused`, `test_the_swing_is_whole_clips` |
| MS4 | The run's Swing is below the Core's size, so the Massager's own trades never take the Position flat or across. | | `test_a_swing_as_large_as_the_core_is_refused` |
| MS5 | Center = (low + high) ÷ 2. Level k is Center + k × Step for k from −levels to +levels, rounded to the nearest tick, so the outer levels sit on the Band's ends or inside them. This lattice prices the catch-up (MS8); after it, levels step out from the anchor (MS9). | | `test_levels_step_out_from_the_center`, `test_a_step_that_does_not_fit_the_band_stays_inside_it` |
| MS6 | A Step must clear the round-trip maker fee at the Center plus one tick: Step ≥ Center × 2 × maker bps ÷ 10,000 + tick. | | `test_a_step_that_does_not_clear_fees_is_refused` |

## The lattice

| # | Rule | Value | Test |
|---|---|---|---|
| MS7 | It sells above the Center and buys below it, whatever the Core's side. Level k stands for a **Lean** of −k × Clip, so the Position stays between Core − Swing and Core + Swing. For a long that is smaller as price rises; for a short it is larger. | | `test_a_short_core_also_sells_above_the_center` |
| MS8 | At start it owes the Lean for the levels price has passed: k₀ is the furthest level at or behind the mid on its side of the Center, and the catch-up is −k₀ × Clip, a sell for k₀ above 0, a buy below, nothing at the Center. It goes on post-only at the touch (phase 2). | | `test_the_catch_up_owes_the_levels_passed`, `test_no_catch_up_at_the_center` |
| MS9 | From level L at its anchor price A it rests a sell at A + Step and A + 2 × Step (levels L + 1, L + 2) and a buy at A − Step and A − 2 × Step (L − 1, L − 2), one Clip each, rounded to the nearest tick, none past ±levels and none outside the Band. The anchor starts at the catch-up level's price, Center + k₀ × Step. Fills at a level add up across its Clips; once they make a whole Clip, that level becomes L, its price before rounding becomes the anchor, and the count starts again. Until then L stays, and the level's next Clip is for what is left. No Clip takes the Lean past the Swing. So every buy-back rests a Step below the sell it follows, whatever the Step is by then, and the other way round. With a Step that never moves this is the lattice of MS5. | 2 each side is code | `test_two_levels_rest_each_side`, `test_the_edge_rests_only_inward`, `test_levels_step_from_the_anchor`, `test_nothing_rests_outside_the_band`, `test_a_full_fill_moves_the_level`, `test_a_partly_filled_level_rests_what_is_left`, `test_no_order_takes_the_lean_past_the_swing`, `test_start_takes_the_core_and_rests_two_levels_each_side`, `test_a_partial_fill_keeps_the_level` |

## What it counts

| # | Rule | Value | Test |
|---|---|---|---|
| MS10 | **Captured** is the Lean's realized profit by average cost, less the Massager's fees (the account's maker fee on each fill). A Clip sold and bought back one Step lower captures Clip × Step less fees. A fill through zero closes what it can and opens the rest at its price. After a live Step shrinks, a round trip can book less than a Step, or below zero, against the Lean's average, though its buy is below its own sell. | | `test_a_round_trip_captures_one_step`, `test_a_fill_through_zero_opens_the_rest`, `test_a_round_trip_moves_the_level_and_captures_one_step` |
| MS11 | **Basis** is the **Tally**'s cost ÷ its size (MS22). The Tally's size is the Position, and its cost is signed like it. A Massager fill adds its signed size × its price, plus its fee, to the cost. An outside add, once the Massager takes it (MS15), adds its size at the mid; an outside reduction takes its share of the cost, so Basis stays. The Tally's entry is the venue entry it began at, moved by an outside add by average cost at the mid; the row shows Basis against it. | | `test_basis_counts_every_massager_trade`, `test_basis_of_a_short_rises_with_a_round_trip`, `test_an_outside_add_moves_basis_at_the_mid`, `test_an_outside_reduction_keeps_basis`, `test_an_outside_add_moves_the_core_and_its_entry` |
| MS12 | Core = Position − Lean, after every fill from outside. A Position flat or on the other side of the Core's side stops the Massager. A Core no larger than the Swing pauses it. Otherwise it runs. Stopping and pausing pull its Clips. | | `test_an_outside_close_stops_it`, `test_a_core_shrunk_to_the_swing_pauses_it`, `test_an_outside_add_keeps_it_running` |

## The job

| # | Rule | Value | Test |
|---|---|---|---|
| MS13 | The catch-up is one post-only Clip at the touch: a sell at the best ask, a buy at the best bid, for what is still owed. When the touch moves it comes off and goes back on at the new one, no faster than every 2 s and not before the venue has shown it (4 s). Once what is owed is under the venue minimum, the lattice starts at the catch-up's level. | 2 s, 4 s are code | `test_the_catch_up_rests_at_the_touch_then_the_lattice_starts`, `test_the_catch_up_follows_the_touch` |
| MS14 | A level that would cross the touch is not sent until it would rest, like a Ladder rung, and a resting Clip the touch has crossed comes off. Price that runs past a level leaves the Lean behind until it comes back. | | `test_a_level_that_would_cross_waits` |
| MS15 | A change of Core counts only once it has held 3 s, so the Massager's own fill seen on the Position before its order row is not taken for an outside one. | 3 s is code | `test_its_own_fill_seen_early_is_not_an_outside_fill`, `test_an_outside_add_moves_the_core_and_its_entry` |
| MS16 | Lean, level, level fills, Captured, Core, Core entry, the catch-up, the anchor, the Step the levels rest at and the Tally are kept with the run. A run kept before the anchor reads back as Fixed, its anchor Center + level × Step. A run kept before the Tally reads back with one built from it: size Core + Lean, cost Core × Core entry − Captured + Lean × the Lean's average, 1 run, begun when the run was. On restart the Clips are pulled as for every Clip algo, the Core is judged again from the Position (MS12), and the lattice goes back on. | | `test_a_run_comes_back_with_its_lean_level_and_core`, `test_a_run_kept_before_the_tally_builds_one` |
| MS17 | Every Clip is a post-only Limit, never reduce-only, and it never sends a Market order. It never places, Amends or cancels a Stop or Take Profit Ticket. | | `test_start_takes_the_core_and_rests_two_levels_each_side` |
| MS18 | One Massager per Market. It runs beside Chase, Ladder and TWAP. It refuses beside a Planner, a Trail or a Grid, and they refuse beside it. Its Clips take client_order_index from `[13e9, 14e9)` ([ADR 0004](adr/0004-partitioned-client-order-index.md)); its runs are `MS-`, named Massager in the journal and in a push. | `[13e9, 14e9)` is code | `test_massager_refuses_beside_planner_trail_or_grid`, `test_its_band_is_an_algo_band`, `test_its_runs_are_named_massager`, `test_a_massager_run_reads_back_with_its_core_lean_and_captured` |

## On the page

| # | Rule | Value | Test |
|---|---|---|---|
| MS19 | **Order ticket → Algo → Massager.** The ticket's size is the Swing, and the size field says so. Under it, in this order: Floor and Ceiling, with one-press Bands from the last 24h range (MS24) and ±1% or ±2% of the mid, and the Chop label beside them; the Step, with the ATR's timeframe (15m, 1h or 4h) at its end and presets of ½, 1 and 2 × ATR(14) that fill it once; and a Follow switch that makes it an ATR Step, where the field takes k and the presets pick k. Then one short grid of what Start would do, worked out the way MS1–MS8 do: the Clip × the levels each side, what one round trip captures, the Position range, the catch-up, the live Step for an ATR run, the run's Swing when it is under the one typed, and the Basis it carries (from which run, its run number) or that it starts new, with a press to start a new Tally (MS22). A refusal replaces the grid in MS1–MS5's own words. With a Massager already on the Market it says so and shows no form (MS18). Start is blocked by the same, and on reduce-only. MS6 needs the account's fee and is the backend's to refuse. It is one action, not Buy or Sell. | ATR(14), 15m / 1h / 4h, ½ / 1 / 2, ±1% / ±2% are code | `web: massager.test.ts`, `web: algoPlugins.test.ts`, `web: MassagerParamsSheet.test.tsx` |
| MS20 | **The working row** shows the Position and its range (Core ∓ Swing), Captured, Core, Lean, Basis against the Tally's entry, the Tally's Captured and its runs, the Band, the Step the levels rest at (for an ATR run also k, the timeframe, the ATR and when the Step last moved), Swing, Clip and level. A run paused by MS23 says which end the candle closed past, and at what. Opened, it lists the live Clips by level and the fills. **The chart** draws the Band's ends and its Center; the resting levels are drawn as orders. | | `web: massager.test.ts` |

## The live Step

| # | Rule | Value | Test |
|---|---|---|---|
| MS21 | An ATR run reads ATR(14) again after each candle of its timeframe closes, on closed candles only. The live Step is k × ATR, kept between the fee floor of MS6 and half the Band. The levels move to it only once it is 20% or more off the Step they rest at: then the resting Clips come off and go back on around the anchor (MS9). A read that fails keeps the Step and tries again in a minute. A Fixed run never moves its Step. The catch-up does not use the Step. | ATR(14), 20%, 1 minute are code | `test_the_live_step_is_kept_between_the_fee_floor_and_half_the_band`, `test_a_small_atr_move_does_not_redraw`, `test_a_small_atr_move_keeps_the_levels`, `test_an_atr_run_redraws_around_the_anchor`, `test_an_atr_run_starts_at_k_times_atr`, `test_no_atr_no_start`, `test_a_fixed_run_never_reads_atr`, `test_atr_reads_closed_candles_only` |

## The Tally

| # | Rule | Value | Test |
|---|---|---|---|
| MS22 | At Start the run carries the **Tally** of the last Massager run on the Market when it fits. A new Tally begins instead, at the venue entry (or the mid without one) with the Position as its size, when the start asks for a fresh one, there was no run, that run ended with its Position closed (MS12), the Position is on the other side, or the Position is not the one it left. A run keeps the venue's size and entry whenever they agree with its Tally. The Position is the one it left when it is the same size at the same entry. When it is smaller and the entry has not moved (a reduction leaves Lighter's entry), the difference is an outside reduction (MS11). When it is larger, the difference is an outside add at the price the entries imply, (entry now × size now − entry then × size then) ÷ the difference, if that is between half and twice the mid. Anything else is a Position closed and opened again between runs. A run that never kept the venue's size and entry carries only to a Position of its Tally's size. The new run's Core is the Position (MS1), so Core a breakout sold or bought stays that way. The Tally's Captured is the earlier runs' plus this run's, and its runs go up by one. | half and twice are code | `test_a_new_run_carries_the_tally`, `test_a_fresh_start_begins_a_new_tally`, `test_a_closed_position_does_not_carry`, `test_the_other_side_does_not_carry`, `test_a_reduction_between_runs_carries_at_basis`, `test_an_add_between_runs_carries_at_the_implied_price`, `test_a_reopened_position_does_not_carry`, `test_a_run_without_the_venue_carries_only_to_the_same_size`, `test_start_carries_the_last_runs_tally`, `test_a_fresh_start_does_not_carry`, `test_the_carry_preview_says_what_a_start_would_take` |

## Leaving the Band

| # | Rule | Value | Test |
|---|---|---|---|
| MS23 | 5 s after each 1h candle closes it reads that candle, closed candles only. A close above the Band's high or below its low pauses it: its Clips come off, the Lean stays, and it says which end and the close (`left_band`), which pushes ([push-rules.md](push-rules.md)). A wick past the Band that closes inside does not. Resume puts the lattice back on; a run still outside pauses again at the next close. A read that fails tries again in a minute. To work new levels, stop it and start a new run: the Tally carries (MS22). | 1h, 5 s, 1 minute are code | `test_a_close_above_the_band_pauses_it`, `test_a_close_below_the_band_pauses_it`, `test_a_close_inside_keeps_it_running`, `test_a_failed_band_read_tries_again`, `test_a_band_check_reads_once_per_close`, `test_resume_does_not_pause_again_on_the_same_close`, `test_the_band_reads_the_last_closed_candle`, `test_a_massager_that_left_the_band_pushes_once` |

## Chop

| # | Rule | Value | Test |
|---|---|---|---|
| MS24 | The ticket reads the last 24 closed 1h candles for a **Chop** reading: the efficiency ratio, \|last close − first close\| ÷ the sum of each close's move from the one before, labelled Ranging under 0.3, Mixed under 0.5 and Trending from 0.5. It suggests a Band from those candles' lowest low to highest high, rounded out to the tick, which one press fills in; with the mid outside that range it suggests none. It never starts, pauses or stops a run. Start sends the reading, and it is kept with the run. | 1h, 24, 0.3, 0.5 are code | `web: massager.test.ts`, `test_the_chop_reading_is_kept_with_the_run` |
