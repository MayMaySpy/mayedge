# Trail rules

What a **Trail** does, start to finish. Change a rule here first, then the code and the test that pins it, in one commit, the same way as [planner-rules.md](planner-rules.md) ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)). The scope it came from is [trail-scope.md](trail-scope.md).

Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here. "code" means the number is not a knob.

Last checked against the code: 2026-10-18.

## Example

A long ZRO Position, mark 2.2000. Trail Stop, start 2.0854, Activation 2.2500, distance 1.5%, on Mark:

- Until mark reaches 2.2500 the stop sits at 2.0854.
- Mark reaches 2.2500. Trigger = 2.2500 × (1 − 1.5%) = 2.21625, rounded away from the best price to 2.2162.
- Step = 10% of the distance = 0.15% of the best price, about 0.0034. Mark goes to 2.2520: the trigger would be 2.2182, only 0.0020 better, so nothing is sent.
- Mark goes to 2.2600: the trigger would be 2.2261, 0.0099 better, and the last move was more than 5s ago. The stop is Amended to 2.2261.
- Mark falls to 2.2261: the venue fires the stop.

## Venue

Lighter has no trailing order type. Its Stop and Take Profit triggers fire on **mark** ([order types](https://docs.lighter.xyz/trading/order-types-and-matching)). A Trail is a desk algo that moves a real Stop by Amend, or sends its own Market order ([ADR 0016](adr/0016-a-trail-is-moved-by-the-desk.md)).

## Inputs

| Input | Values | Notes |
|---|---|---|
| Kind | Entry, Stop, Take Profit | |
| Side | buy, sell | For an Entry, the order's side. For Stop and Take Profit, the closing side, taken from the Position. |
| Size | size | Entry only. |
| Size % | 1–100 | Take Profit only. % of the Position at start. |
| Start | price | Stop only. Optional. |
| Activation | price | Required on a Take Profit. Optional on Entry and Stop. |
| Distance | %, or price | |
| Reference | Mark, Last | |
| Expiry | minutes, or none | Entry only. |
| Slippage | % | The order ticket's setting, capped at 5% like every Market order. |

## Follow

| | Rule | Knob | Pinned by |
|---|---|---|---|
| F1 | The **best price** is the highest of the Reference since activation for a long exit or a short entry, and the lowest for a short exit or a long entry. | | test_best_price_follows_the_favourable_side |
| F2 | Trigger = best price − distance for a long exit or a short entry, + distance for a short exit or a long entry. A % distance is a % of the best price. | | test_trigger_sits_the_distance_behind_the_best_price |
| F3 | The trigger rounds to the tick away from the best price. | code | test_trigger_rounds_away_from_the_best_price |
| F4 | The trigger moves only toward the better side. Nothing moves it back: not the desk, and not an Edit. | | test_trigger_never_moves_back, test_an_edit_never_moves_the_trigger_back |
| F5 | With an Activation, the Trail does not follow until the Reference reaches that price. A long exit waits for price at or above it, a long entry for price at or below it. | | test_activation_waits_for_its_price |
| F6 | A venue order moves only when the trigger beats the order's by at least the **step**, and at least the **min gap** after its last move. | step: max(10% of the distance, 2 ticks); min gap: 5s | test_a_move_smaller_than_the_step_is_not_sent, test_moves_wait_the_min_gap |
| F7 | All Trails on one Market send at most 15 Amends a minute between them. | code | test_a_market_shares_one_amend_budget |
| F8 | Firing is never held back by the step, the gap or F7. | | test_a_fire_is_not_held_by_the_gap |
| F9 | On Last, the best price comes from every public trade print on its Market, and the desk keeps that Market's trades for as long as the Trail runs. | | test_last_follows_every_print |
| F10 | While the market feed is not live, a Trail does not follow or fire. It says `not following`. Venue orders it already has stay where they are. | | test_a_stale_feed_stops_following |

## Entry

| | Rule | Knob | Pinned by |
|---|---|---|---|
| TE1 | The desk holds the trigger. When the Reference crosses it, the desk sends a Market order for the size at the slippage cap. While the desk is down it does not fire. | | test_entry_fires_a_market_order_when_price_comes_back |
| TE2 | An entry that has not fired by its expiry ends unfilled. | `expiry` input | test_an_expired_entry_ends_unfilled |
| TE3 | A fill counts only with evidence from trades or the account feed ([ADR 0003](adr/0003-invent-fill-needs-evidence.md)). The entry ends once its Market order is done. | | test_entry_ends_once_its_order_is_done |
| TE4 | A standalone entry places no stop. A trailing entry with a stop and targets is a Planner with a Trail entry. | | |

## Stop

| | Rule | Knob | Pinned by |
|---|---|---|---|
| TS1 | It needs an open Position. Its stop goes on the venue at start: at the Start price, or else at mark − distance for a long (+ for a short). | | test_the_stop_goes_on_at_start |
| TS2 | Before activation the stop holds at its start price. After it, the trigger is the further of the start price and F2. | | test_the_stop_holds_until_activation |
| TS3 | It is a reduce-only Stop Market tied to the Position (size 0), so adds and partial closes need no Amend. | | test_the_stop_goes_on_at_start |
| TS4 | Starting it cancels the Market's **Stop** Tickets after its own stop is on. **Take Profit** Tickets stay. The confirm names each Stop it cancels. While it runs, the Stop editor refuses a new Stop on the Market. | | test_a_trail_stop_replaces_stop_tickets, test_the_stop_editor_refuses_beside_a_trail_stop |
| TS5 | It ends when the Position is flat. | | test_flat_ends_the_trail |

## Take Profit

| | Rule | Knob | Pinned by |
|---|---|---|---|
| TT1 | It needs an open Position and an Activation on the profit side of mark. Until activation nothing is on the venue. | | test_take_profit_needs_an_activation_past_mark |
| TT2 | Its size is the Size % of the Position at start, rounded down to the lot, and at least the venue minimum. | | test_take_profit_size_is_a_share_of_the_position |
| TT3 | At activation it places a reduce-only Stop Market for its size at the F2 trigger, and follows. | | test_take_profit_places_its_stop_at_activation |
| TT4 | It sits beside the Position's Stop and Take Profit Tickets. Every leg is reduce-only. | | |
| TT5 | It ends once its stop has filled, or the Position is flat. | | test_take_profit_ends_when_its_stop_fills |

## Last

| | Rule | Knob | Pinned by |
|---|---|---|---|
| L1 | An exit on Last is fired by the desk: when a print goes through the trigger, it sends a reduce-only Market order for the exit's size. | | test_an_exit_on_last_fires_on_a_print |
| L2 | Its venue Stop is a **backstop** one step behind the trigger. It holds the exit while the desk is down. | | test_the_backstop_sits_one_step_behind |
| L3 | Once the desk has fired, it cancels the backstop. If both fire, both are reduce-only: a partial exit can close up to twice its size, never more than the Position. The confirm says so. | | test_the_backstop_comes_off_after_a_fire |

## Venue

| | Rule | Knob | Pinned by |
|---|---|---|---|
| V1 | If its venue stop leaves the book while the Position is open and the Trail has not fired, the desk puts it back at the current trigger. | code | test_a_missing_stop_is_put_back |
| V2 | If the venue refuses a stop or an Amend as "wrong side of mark", price is already through it. The desk closes the exit's size with a reduce-only Market order. | | test_a_stop_mark_has_passed_closes_at_market |
| V3 | Its Clips use the client_order_index band 12e9–13e9 ([ADR 0004](adr/0004-partitioned-client-order-index.md)). | | test_trail_cois_are_in_their_band |
| V4 | The best price, activation and trigger are saved with the run. A restart carries on from them. It does not rebuild what it missed while the desk was down. | | test_a_restart_carries_on_from_the_saved_best_price |
| V5 | While the desk is down, a venue stop holds at the last price it was moved to. An entry, or an exit not yet activated, waits. | | test_shutdown_leaves_the_stop_on |

## Start and end

| | Rule | Knob | Pinned by |
|---|---|---|---|
| S1 | A Trail refuses beside a Planner (Planner runs its own) or Grid ([ADR 0002](adr/0002-grid-is-exclusive-on-a-market.md)), and they refuse beside it. | | test_trail_refuses_beside_planner_or_grid |
| S2 | Per Market at once: one Entry, one Stop, three Take Profits. | code | test_one_trail_stop_per_market |
| S3 | A distance under 2 ticks, an Activation on the wrong side of mark, or a Start on the wrong side of mark or past the **Liquidation price** refuses. | | test_bad_inputs_refuse |
| S4 | **Kill**, or Cancel all on its Market, stops every Trail there and cancels its orders. | | test_cancel_all_stops_the_trails |
| S5 | Stopping a Trail Stop offers **Keep stop**: a plain Stop Ticket goes on at the current trigger, then the Clip comes off. **Cancel stop** pulls it and leaves the Position with no stop. | | test_stop_keep_leaves_a_stop_ticket |
| S6 | The chart draws a Trail's lines but does not drag them ([ADR 0007](adr/0007-chart-amends-tickets-only.md)). | | |

## In Planner

Planner runs its own Trails: a Trail entry, a Trail stop for what is left, and Trail targets. Their rules are in [planner-rules.md](planner-rules.md) (E9, M10, M11, P9) and follow F1–F10 and L1–L3 here.
