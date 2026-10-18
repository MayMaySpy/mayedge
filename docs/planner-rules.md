# Planner rules

What the **Planner** algo does, start to finish. Change a rule here first, then the code and the test that pins it, in one commit, the same way as [alert-rules.md](alert-rules.md) ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)).

Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here. "code" means the number is not a knob.

Last checked against the code: 2026-10-18.

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
| Entry type | Market, Limit, Trail | Enter only. A Trail entry also takes an Activation (optional) and a distance (% or price). |
| Entry price | price | Limit only. A Market entry plans from mark at send. |
| Stop | price | Required. It defines **R**. |
| Size | size, or risk % of equity | Enter only. Attach takes the Position's size. |
| Targets | list of (price or R multiple, % of the Position, Limit, Trigger or Trail) | At least one, or none with a Trail stop. The %s add up to 100 or less. Limit by default. A Trail target also takes a distance (R or %). |
| Stop steps | Off, Breakeven, Step up | Breakeven by default. |
| Trail stop | Off, after a target, after the last target, or at an R multiple; distance in R or % | Off by default. |
| Reference | Mark, Last | What every Trail part of the plan follows ([trail-rules.md](trail-rules.md)). Mark by default. |
| Entry expiry | minutes, or none | Limit or Trail. |
| Slippage | % | Market entry and Market stop. The order ticket's setting, capped at 5% like every Market order. |

## Plan

| | Rule | Knob | Pinned by |
|---|---|---|---|
| P1 | **R** is the distance from entry to the stop. Before the fill, entry is the Limit price, or mark for a Market entry. After it, entry is the Position's average entry. | code | test_r_targets_reprice_from_the_actual_entry |
| P2 | Size from risk is equity × risk % ÷ (R + the taker fee per unit at the stop), rounded down to the lot. Equity is the Portfolio margin the header shows at send. Size is fixed once sent. A Trail entry is sent when it fires, so its size is worked out from the price it fires at. | code | test_size_from_risk_rounds_down_to_the_lot, test_size_from_risk_pays_the_taker_fee_at_the_stop |
| P3 | After the fill, the plan shows the risk at its actual entry. Slippage can make it differ from P2. | | test_targets_go_on_once_the_entry_is_complete_from_its_actual_price |
| P4 | A target given in R is priced from the entry, and moves to the actual entry once filled. A target given as a price stays where it was put. | | test_r_targets_reprice_from_the_actual_entry, test_targets_go_on_once_the_entry_is_complete_from_its_actual_price |
| P5 | Each target closes a % of the filled size. The %s add up to at most 100. Whatever is left is the **Runner**. It rides on the stop, which may trail, until the Position closes. | | test_what_no_target_closes_is_the_runner, test_targets_over_100_pct_are_refused |
| P6 | Prices round to the tick: the stop away from entry, targets toward it. Sizes round down to the lot. The last target takes what rounding leaves, never the Runner. | code | test_prices_round_to_the_tick_the_safe_way, test_the_last_target_takes_the_rounding_not_the_runner |
| P7 | A target whose size is below the venue minimum joins the next target, and takes that target's order type. The last one joins the one before it. A plan left with no target refuses to start. | code | test_a_small_target_joins_the_next_one, test_a_small_last_target_joins_the_one_before, test_a_size_too_small_for_any_target_is_refused |
| P8 | Percentages on a plan are from entry. | | test_percentages_are_from_entry |
| P9 | The stop is a Stop Market with the slippage input. Each target is the order type picked for it, at its own price. A **Limit** is a reduce-only limit that rests on the book from the moment targets go on. A **Trigger** is a Take Profit Limit that waits off the book until mark reaches it. A **Trail** target waits off the book until the Reference reaches its price, then puts on a reduce-only Stop Market for its size and follows the best price at its distance ([trail-rules.md](trail-rules.md) TT3). A target saved without a type is a Trigger, which is what every target was before the choice. | | test_the_stop_goes_on_with_the_first_fill, test_a_take_profit_limit_rests_at_its_price, test_a_limit_target_rests_on_the_book, test_a_target_without_a_type_is_a_trigger |

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
| E1 | The entry is a Planner Clip, not a Ticket. A Limit entry rests at its price and may fill as taker if it crosses. A Market entry uses the slippage input. A **Trail** entry is held by the desk: it follows the best price from its Activation and sends a Market entry when the Reference comes back by its distance ([trail-rules.md](trail-rules.md) TE1). | | test_the_entry_is_a_clip_on_planners_band |
| E2 | The stop goes on with the first fill. It is tied to the Position, not to a size, so it covers every later fill without an Amend. | | test_the_stop_goes_on_with_the_first_fill |
| E3 | Targets go on once the entry is complete, or once what is left of it is cancelled. | | test_targets_go_on_once_the_entry_is_complete_from_its_actual_price |
| E4 | If mark reaches the stop before the entry is complete, Planner cancels the rest of the entry. | | test_mark_through_the_stop_cancels_the_entry |
| E5 | When the entry expires, Planner cancels the rest and protects what filled. | `expiry` input | test_an_expired_entry_protects_what_filled |
| E6 | An entry that ends with nothing filled ends the Planner. | | test_an_entry_that_never_fills_ends_the_planner |
| E7 | A fill counts only with evidence from trades or the account feed. A Clip that vanishes is not a fill ([ADR 0003](adr/0003-invent-fill-needs-evidence.md)). | | test_a_vanished_entry_is_not_a_fill |
| E8 | If mark is already through the stop when the stop should go on, the venue will not take it. Planner closes what is open with a reduce-only Market order instead, as the stop would have. | | test_a_stop_mark_has_passed_closes_at_market |
| E9 | A Trail entry that fires sizes from the fire price (P2), checks S1 again, and goes out as a Market entry. If the Reference reaches the stop first, it ends without firing (E4). | | test_a_trail_entry_fires_and_sizes_from_its_price, test_a_trail_entry_through_the_stop_ends |

## Manage

| | Rule | Knob | Pinned by |
|---|---|---|---|
| M1 | The stop always covers the whole open Position. It is tied to the Position, so a target fill shrinks what it closes. | | test_the_stop_goes_on_with_the_first_fill |
| M2 | When a target has filled in full, the stop takes a **Stop step**. With Breakeven, TP1 (the target nearest entry) moves it to **Breakeven**. With Step up, TP1 moves it to Breakeven and each later target moves it to the price of the target before it: TP2 to TP1, TP3 to TP2. A step after which nothing would be left open is not drawn. A step to a Trail target goes to the price it filled at, not the price it activated at. | `stop_steps` input | test_breakeven_once_the_first_target_fills, test_step_up_moves_the_stop_to_the_target_before |
| M3 | **Breakeven** is entry plus the round-trip taker fee per unit for a long, minus it for a short, rounded away from entry. Closing there loses nothing. | code | test_breakeven_covers_the_round_trip_fee |
| M4 | Planner moves the stop only toward the winning side. Stop steps and the **Trail stop** are the only moves it makes on its own. The stop is the further of the two. When targets fill faster than it can step, it takes the furthest step that is due, once. | | test_breakeven_never_loosens_the_stop, test_two_targets_at_once_take_the_furthest_step |
| M5 | The operator changes a plan through Planner. A change is checked against S1 and S2 as if it were new. A new trail distance never moves a live trigger back. Planner's Clips do not drag on the chart ([ADR 0007](adr/0007-chart-amends-tickets-only.md)). | | test_a_replan_moves_the_stop_and_redraws_the_targets |
| M6 | When the Position's size changes by anything other than Planner's own fills, Planner pauses and says the Position changed. A paused Planner leaves its stop and targets on the venue. It stops resizing them and takes no Stop step until the operator re-plans or resumes. | | test_an_outside_change_pauses_the_planner |
| M7 | The stop and targets are venue triggers, so they hold while the desk is down. On restore, Planner reads the fills it missed and applies M1 and M2. A trailing part holds where it was while the desk is down, and carries on from the best price it saved. A Trail target that has not activated waits, unlike a Trigger target. | | test_a_restart_applies_the_target_fill_it_missed, test_shutdown_leaves_the_stop_and_targets_on |
| M8 | If the stop leaves the book while the Position is still open, Planner puts it back. | code | test_a_missing_stop_is_put_back |
| M9 | If mark is already past a step when its target fills, the venue will not take the stop there. A step to Breakeven waits for mark to clear it. A step to a target's price closes what is left with a reduce-only Market order, the exit the step was there to keep. | code | test_breakeven_waits_while_mark_sits_on_it, test_a_step_mark_has_passed_closes_at_market |
| M10 | Once its start is reached (a target filled in full, the last target filled, or the Reference at an R multiple), the **Trail stop** follows the best price at its distance, with the stepped stop as its floor ([trail-rules.md](trail-rules.md) F1–F8). On Last, Planner closes on a print and keeps the venue stop one step behind as a backstop (L1–L3). | | test_the_trail_stop_starts_after_its_target, test_the_trail_stop_never_goes_below_the_stepped_stop, test_the_trail_stop_starts_at_an_r_multiple |
| M11 | A paused Planner (M6) does not trail, activate a Trail target, or fire a Trail entry. | | test_a_paused_planner_does_not_trail |

## End

| | Rule | Knob | Pinned by |
|---|---|---|---|
| N1 | Planner ends when the Position is flat: at the stop, at the last target, or closed by the operator. It cancels whatever of its Clips are left. | | test_flat_ends_the_planner |
| N2 | **Kill**, or Cancel all on its Market, stops Planner and cancels its stop with every other working order. Without a flatten, the Position is left with no stop. The Kill dialog says so while a Planner is live. | | test_cancel_all_on_its_market_stops_the_planner, warns that Stop + cancel leaves a Planner's Position with no stop |
| N3 | Auto kill is independent of Planner. | | |
| N4 | Stopping a Planner cancels all its Clips, the stop with them. The confirm says the Position is left with no stop. | | test_stopping_cancels_every_clip |
