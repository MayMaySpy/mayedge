# Planner rules

What the **Planner** algo does, start to finish. Change a rule here first, then the code and the test that pins it, in one commit, the same way as [alert-rules.md](alert-rules.md) ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)).

Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here. "code" means the number is not a knob.

Last checked against the code: 2026-10-17.

## Example

A long ZRO plan, entered at 2.19082 with the stop at 2.0854 and $5,537 of equity:

- **R** = 2.19082 − 2.0854 = 0.10542.
- Risk at the stop for 100 ZRO = 100 × 0.10542 = $10.54, or 0.19% of equity.
- At 1% risk, size = 55.37 ÷ 0.10542 = 525 (before fees).
- A target at 2R sits at 2.19082 + 2 × 0.10542 = 2.40166. At 3R it sits at 2.50708.
- Once the first target fills, the stop moves to 2.19082 plus fees.

Every number in a plan comes from the one stop. There is no second, suggested stop.

## Inputs

| Input | Values | Notes |
|---|---|---|
| Mode | Enter, Attach | Enter sends the entry. Attach takes over a Position already open. |
| Side | long, short | Attach takes it from the Position. |
| Entry type | Market, Limit | Enter only. |
| Entry price | price | Limit only. A Market entry plans from mark at send. |
| Stop | price | Required. It defines **R**. |
| Size | size, or risk % of equity | Enter only. Attach takes the Position's size. |
| Targets | list of (price or R multiple, % of the Position) | At least one. The %s add up to 100 or less. |
| Breakeven | on, off | On by default. |
| Entry expiry | minutes, or none | Limit only. |
| Slippage | % | Market entry and Market stop. The order ticket's setting, capped at 5% like every Market order. |

## Plan

| | Rule | Knob | Pinned by |
|---|---|---|---|
| P1 | **R** is the distance from entry to the stop. Before the fill, entry is the Limit price, or mark for a Market entry. After it, entry is the Position's average entry. | code | test_r_targets_reprice_from_the_actual_entry |
| P2 | Size from risk is equity × risk % ÷ (R + the taker fee per unit at the stop), rounded down to the lot. Equity is the Portfolio margin the header shows at send. Size is fixed once sent. | code | test_size_from_risk_rounds_down_to_the_lot, test_size_from_risk_pays_the_taker_fee_at_the_stop |
| P3 | After the fill, the plan shows the risk at its actual entry. Slippage can make it differ from P2. | | test_targets_go_on_once_the_entry_is_complete_from_its_actual_price |
| P4 | A target given in R is priced from the entry, and moves to the actual entry once filled. A target given as a price stays where it was put. | | test_r_targets_reprice_from_the_actual_entry, test_targets_go_on_once_the_entry_is_complete_from_its_actual_price |
| P5 | Each target closes a % of the filled size. The %s add up to at most 100. Whatever is left is the **Runner**. It rides on the stop until the Position closes. | | test_what_no_target_closes_is_the_runner, test_targets_over_100_pct_are_refused |
| P6 | Prices round to the tick: the stop away from entry, targets toward it. Sizes round down to the lot. The last target takes what rounding leaves, never the Runner. | code | test_prices_round_to_the_tick_the_safe_way, test_the_last_target_takes_the_rounding_not_the_runner |
| P7 | A target whose size is below the venue minimum joins the next target. The last one joins the one before it. A plan left with no target refuses to start. | code | test_a_small_target_joins_the_next_one, test_a_small_last_target_joins_the_one_before, test_a_size_too_small_for_any_target_is_refused |
| P8 | Percentages on a plan are from entry. | | test_percentages_are_from_entry |
| P9 | The stop is a Stop Market with the slippage input. Each target is a Take Profit Limit at its own price. | | test_the_stop_goes_on_with_the_first_fill, test_a_take_profit_limit_rests_at_its_price |

## Start

A plan that breaks a rule here does not start, and says which rule.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| S1 | The stop is on the losing side of both entry and mark. Every target is on the winning side of both. | | test_a_stop_on_the_winning_side_is_refused, test_a_stop_mark_has_passed_is_refused, test_a_target_behind_entry_is_refused |
| S2 | When the Position has a **Liquidation price**, the stop sits before it. | | test_a_stop_beyond_the_liquidation_price_is_refused |
| S3 | Enter refuses while a Position is open on the Market. That is what Attach is for. | | test_enter_refuses_with_a_position_open |
| S4 | Attach refuses without an open Position. | | test_attach_refuses_without_a_position, test_attach_refuses_the_other_side |
| S5 | One Planner per Market. It refuses while any other desk algo is live on that Market, and Grid refuses while a Planner is ([ADR 0002](adr/0002-grid-is-exclusive-on-a-market.md)). | | test_one_planner_per_market, test_planner_refuses_beside_another_desk_algo, test_grid_and_planner_each_refuse_beside_another_algo |
| S6 | Attach cancels every **Stop** and **Take Profit** Ticket on the Market and replaces them with its own. Its stop goes on first, so the Position is never without one. The confirm names each one it cancels ([ADR 0015](adr/0015-planner-owns-the-exit.md)). | | test_attach_puts_its_stop_on_before_pulling_tickets |
| S7 | While a Planner is live on a Market, the Positions Stop / Take Profit editor refuses on that Market, and so does an Amend of a Planner Clip outside Planner. | | test_the_stop_editor_refuses_on_a_planner_market, test_the_stop_editor_never_replaces_an_algos_stop |

## Entry

| | Rule | Knob | Pinned by |
|---|---|---|---|
| E1 | The entry is a Planner Clip, not a Ticket. A Limit entry rests at its price and may fill as taker if it crosses. A Market entry uses the slippage input. | | test_the_entry_is_a_clip_on_planners_band |
| E2 | The stop goes on with the first fill. It is tied to the Position, not to a size, so it covers every later fill without an Amend. | | test_the_stop_goes_on_with_the_first_fill |
| E3 | Targets go on once the entry is complete, or once what is left of it is cancelled. | | test_targets_go_on_once_the_entry_is_complete_from_its_actual_price |
| E4 | If mark reaches the stop before the entry is complete, Planner cancels the rest of the entry. | | test_mark_through_the_stop_cancels_the_entry |
| E5 | When the entry expires, Planner cancels the rest and protects what filled. | `expiry` input | test_an_expired_entry_protects_what_filled |
| E6 | An entry that ends with nothing filled ends the Planner. | | test_an_entry_that_never_fills_ends_the_planner |
| E7 | A fill counts only with evidence from trades or the account feed. A Clip that vanishes is not a fill ([ADR 0003](adr/0003-invent-fill-needs-evidence.md)). | | test_a_vanished_entry_is_not_a_fill |
| E8 | If mark is already through the stop when the stop should go on, the venue will not take it. Planner closes what is open with a reduce-only Market order instead, as the stop would have. | | test_a_stop_mark_has_passed_closes_at_market |

## Manage

| | Rule | Knob | Pinned by |
|---|---|---|---|
| M1 | The stop always covers the whole open Position. It is tied to the Position, so a target fill shrinks what it closes. | | test_the_stop_goes_on_with_the_first_fill |
| M2 | Once the first target, the one nearest entry, has filled in full, the stop moves to **Breakeven**. | `breakeven` input | test_breakeven_once_the_first_target_fills, test_breakeven_waits_while_mark_sits_on_it |
| M3 | **Breakeven** is entry plus the round-trip taker fee per unit for a long, minus it for a short, rounded away from entry. Closing there loses nothing. | code | test_breakeven_covers_the_round_trip_fee |
| M4 | Planner moves the stop only toward the winning side. Breakeven is the only move it makes on its own. | | test_breakeven_never_loosens_the_stop |
| M5 | The operator changes a plan through Planner. A change is checked against S1 and S2 as if it were new. Planner's Clips do not drag on the chart ([ADR 0007](adr/0007-chart-amends-tickets-only.md)). | | test_a_replan_moves_the_stop_and_redraws_the_targets |
| M6 | When the Position's size changes by anything other than Planner's own fills, Planner pauses and says the Position changed. A paused Planner leaves its stop and targets on the venue. It stops resizing them and makes no Breakeven move until the operator re-plans or resumes. | | test_an_outside_change_pauses_the_planner |
| M7 | The stop and targets are venue triggers, so they hold while the desk is down. On restore, Planner reads the fills it missed and applies M1 and M2. | | test_a_restart_applies_the_target_fill_it_missed, test_shutdown_leaves_the_stop_and_targets_on |
| M8 | If the stop leaves the book while the Position is still open, Planner puts it back. | code | test_a_missing_stop_is_put_back |

## End

| | Rule | Knob | Pinned by |
|---|---|---|---|
| N1 | Planner ends when the Position is flat: at the stop, at the last target, or closed by the operator. It cancels whatever of its Clips are left. | | test_flat_ends_the_planner |
| N2 | **Kill**, or Cancel all on its Market, stops Planner and cancels its stop with every other working order. Without a flatten, the Position is left with no stop. The Kill dialog says so while a Planner is live. | | test_cancel_all_on_its_market_stops_the_planner, warns that Stop + cancel leaves a Planner's Position with no stop |
| N3 | Auto kill is independent of Planner. | | |
| N4 | Stopping a Planner cancels all its Clips, the stop with them. The confirm says the Position is left with no stop. | | test_stopping_cancels_every_clip |

## Later

- Trailing the **Runner** (v2).
