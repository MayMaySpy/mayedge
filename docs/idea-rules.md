# Idea rules

What an **Idea** stores and what the Ideas page may do with it. Change a rule here first, then the code and the test that pins it, in one commit, the same way as [alert-rules.md](alert-rules.md) ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)).

Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here. "code" means the number is not a knob. The page writes only to the desk database ([ADR 0020](adr/0020-an-idea-is-a-note-not-an-order.md)).

## Shape

| | Rule | Knob | Pinned by |
|---|---|---|---|
| I1 | An Idea is one Market, by symbol, and one side. The symbol is stored upper case. A symbol the venue no longer lists keeps its Idea; the page shows "Not listed" and no price. | | test_an_unlisted_market_keeps_its_idea |
| I2 | An Idea cannot be saved without a Thesis of at least 10 characters after trimming. Everything else is optional at creation. | code | test_an_idea_needs_a_thesis |
| I3 | More than one Idea per Market is allowed (a long and a short, or a new one after a Closed one). The page warns when a second open Idea (Watching or Active) is made on the same Market and side. It still saves. | | test_a_second_open_idea_on_a_market_warns |
| I4 | Tags are lower case, trimmed, 1–24 characters, at most 8 per Idea, de-duplicated. They are the narratives ("ai", "l2", "rwa", "unlock"). | code | test_tags_are_normalised |
| I5 | Catalysts are at most 12 per Idea: text up to 120 characters and an optional UTC date (`YYYY-MM-DD`). Sorted by date, undated last. | code | test_catalysts_sort_by_date |
| I6 | Prices are stored as decimal strings, as typed, and never as floats. | | test_prices_round_trip_as_typed |
| I7 | Conviction is 1, 2 or 3. A new Idea is 2. Horizon is scalp, swing or position. A new Idea is swing. | code | test_a_new_idea_is_watching |

## Plan

A long ZRO plan, zone 2.18–2.20 with the stop at 2.08:

- Plan entry = (2.18 + 2.20) / 2 = 2.19.
- **R** = 2.19 − 2.08 = 0.11.
- A target at 2.40 is 0.21 / 0.11 = 1.91R.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| P1 | A Plan has an Entry zone (`entry_low`, `entry_high`), a stop and 0–4 Targets. A single entry price is stored as low = high. low ≤ high, all > 0. A zone missing one end is refused. | code | test_a_zone_is_low_then_high |
| P2 | Long: the stop is below `entry_low`, every Target is above `entry_high`. Short: the mirror. A Plan that breaks this is refused with the field that breaks it. Checked once both ends of the zone and that field are set. | | test_a_long_stop_sits_below_the_zone, test_a_short_target_sits_below_the_zone |
| P3 | The plan entry is the zone's midpoint. **R** = \|plan entry − stop\|. A Target's R multiple is its distance from the plan entry over R, to 2 decimal places, half up. | code | test_targets_are_measured_from_the_midpoint |
| P4 | A Target is stored as a price. The editor accepts an R multiple and converts it to a price at the Market's `price_decimals`, using P3. | code | `web: ideas.test.ts` |
| P5 | Target sizes are optional percents of the Position that add up to 100 or less. No targets: the Draft uses the Planner's default, 2R at 50% and 3R at 50%. Targets and no percents: each gets an equal whole-percent share of 100, the last taking the remainder (two targets is 50/50). Stated percents are handed through; an unsized target then shares what is left of 100. | code | test_target_shares_add_up_to_100_or_less, `web: ideas.test.ts` |
| P6 | A Plan is complete with a zone and a stop. Only a complete Plan can go to the chart (D1). | | test_a_plan_needs_a_zone_and_a_stop |

The Draft carries the plan entry, the stop and the Targets. It does not carry the zone's low and high. A Ladder entry across the zone is not this hand-off; it waits until a Draft can carry from and to.

## Status

Watching, Active, Closed, Dropped. Stored in lower case.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| S1 | A new Idea is Watching. | | test_a_new_idea_is_watching |
| S2 | Watching → Active when the operator marks it, or when a Planner is started from its Draft (D4). Active → Closed by the operator. Watching or Active → Dropped by the operator. Closed or Dropped → Watching is a reopen. No other move. | | test_status_moves |
| S3 | The desk never moves a status on price. In zone and Past stop are shown, never acted on. | | test_price_never_moves_a_status |
| S4 | Every status move and every Plan change writes one Idea log line, with Last at that moment if the desk has one. A Plan change line names what moved: `Entry 2.30–2.35 → 2.28–2.33 · Stop 2.08 → 2.12`. Empty when nothing in the Plan moved, and then no line is written. | | test_a_plan_change_is_logged, test_plan_diff_names_what_moved |
| S5 | Closed and Dropped Ideas ask for a Review: outcome Worked, Failed, Missed (never entered, it went without us) or Wrong (invalidated before entry), and free text. Optional, editable later. A reopen does not clear it. | | test_a_review_is_optional, test_review_outcomes |
| S6 | Delete removes an Idea and its log for good. The page asks first and names the Idea. Dropped is the normal way out. | | test_delete_removes_the_log |

Times are milliseconds.

A patch of the Idea sends the `updated_at` the page last saw (`seen_updated_at`). An older one is refused with 409 and the page reloads that Idea. Pinned by `test_a_stale_patch_is_409`.

## Live

All on the page, from `GET /api/markets`. Last on a log line uses the same rule, from the market the desk already holds. No venue call.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| L1 | Last is the Market's last trade, else mark, else mid. Missing, zero or non-finite is unknown, not `0`. | | `web: ideas.test.ts`, test_last_is_the_trade_else_the_mark_else_the_mid |
| L2 | **To entry** is the signed percent from Last to the nearest zone edge, over Last. `0` inside the zone (L3). Outside, raw = (edge − Last) / Last × 100. A long shows −raw, a short shows raw: long above the zone and short below it are positive (price must come back); the other side is negative (price must go through). | code | `web: ideas.test.ts` |
| L3 | **In zone**: `entry_low` ≤ Last ≤ `entry_high`. A single price (low = high) counts as in zone within 0.25% of that price: \|Last − price\| / price ≤ 0.0025. | code | `web: ideas.test.ts` |
| L4 | **Past stop**: a Watching Idea whose Last is at or beyond its stop. Long: Last ≤ stop. Short: Last ≥ stop. | | `web: ideas.test.ts` |
| L5 | **R now**: for an Active Idea, (Last − plan entry) / R for a long, the mirror for a short. Unknown without a complete Plan or a Last. | code | `web: ideas.test.ts` |
| L6 | The page reads `/api/markets` every 10 s while visible, and the Ideas every 60 s and after each save. It opens no desk socket ([ADR 0001](adr/0001-watch-is-a-desk-view.md)). | code | `IdeasPage` tests |

## Draft hand-off

The Draft is a copy of the Plan at send time. Later edits to the Idea do not move it.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| D1 | **Draft on chart** sends one message on the desk channel: symbol, side, plan entry, stop, Targets as R multiples with their percents, and the Idea id. Only for a complete Plan (P6). | | `deskBridge` tests |
| D2 | The desk answers a ping within 500 ms when its tab is open. Without an answer, the page opens the desk at `/{SYMBOL}` in a new tab and sends the Draft once that tab says hello. One desk tab, never two. | code | `IdeasPage` tests |
| D3 | The desk switches to the Market, replaces that Market's Draft with the Idea's (a toast says so when it replaced one), and opens the Planner dialog. Nothing reaches the venue until **Start** ([ADR 0018](adr/0018-the-chart-drafts-a-planner.md)). A Market where a Planner already runs shows the dialog's own refusal ([ADR 0015](adr/0015-planner-owns-the-exit.md)). | | `chartDraft` tests |
| D4 | When a Planner starts from that Draft, the desk writes `POST /api/ideas/{id}/planner` with the algo id. The Idea goes Active (S2) and its log names the Planner. The write is idempotent per algo id. If the write fails, the Planner still runs; a toast says the Idea was not updated. | | test_a_planner_start_marks_the_idea_active |
| D5 | An Idea's Round trips are the Journal's on its Market whose open time is at or after the Idea's creation, and before it was Closed or Dropped if it was. A journal timestamp below 10^12 is seconds. | code | `web: ideas.test.ts` |

## Price alerts

A **Price alert** tells the operator a price was reached. It is a toast, a Push and an Idea log line, and nothing else: it never places, amends or cancels an order, and never moves an Idea's status ([ADR 0021](adr/0021-a-price-alert-is-a-push-not-an-order.md)). Pushes follow [push-rules.md](push-rules.md) (the `ideas` knob).

A long ZRO Idea with Last at 2.15:

- A Level at 2.20 is set **above** (2.20 is over Last). It fires when Last is 2.20 or more.
- A Move of 5% either way has its base at 2.15. It fires at 2.2575 or more, or 2.0425 or less.
- A Day of 10% up fires when the Daily Change is +10% or more.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| A1 | A Price alert belongs to one Idea and watches that Idea's Market. Its kind is **Level**, **Move** or **Day**. An Idea holds at most 20, armed or fired. Deleting the Idea deletes them. | code | test_an_idea_holds_at_most_20_alerts, test_deleting_the_idea_deletes_its_alerts |
| A2 | A Level has a price (a decimal string above 0, kept as typed) and a direction, **above** or **below**. Without a direction it is taken from Last when the alert is armed: above when the price is over Last, below when under. A price equal to Last, or no Last and no direction, is refused. It is met when Last ≥ price (above) or Last ≤ price (below). | | test_a_level_takes_its_direction_from_last, test_a_level_at_last_is_refused |
| A3 | A Move has a percent above 0 and at most 100, and a direction **up**, **down** or **either** (either by default). Its base is Last when it is armed; with no Last it is refused. It is met when (Last − base) / base × 100 is at least the percent (up), at most minus the percent (down), or either. | code | test_a_move_is_measured_from_its_base |
| A4 | A Day has a percent above 0 and at most 100 and a direction up, down or either (either by default). It is met when the **Daily Change** is at least +percent (up), at most −percent (down), or either. One already met when it is armed is refused, with the Daily Change now. | code | test_a_day_already_met_is_refused |
| A5 | Last is L1's. A missing Last, or a missing Daily Change for a Day, is unknown: the alert waits. It never fires on an unknown. | | test_an_alert_waits_without_a_last |
| A6 | Only alerts on a Watching or Active Idea are checked. Closing or dropping the Idea stops the checks and leaves the alerts as they are; a reopen checks them again. | | test_alerts_on_a_closed_idea_wait |
| A7 | The desk checks armed alerts every 2 seconds, only while it runs. An alert armed before the desk started and already met at its first look fires then, and its text says it was met when the desk started. | code | test_an_alert_met_at_start_says_so |
| A8 | **Once** (the default): a fired alert stays, marked fired with the time and Last. **Re-arm** arms it again as if new: a Level takes its direction from Last now, a Move its base. **Repeat**: the desk re-arms it the same way 15 minutes after it fired, and a Day only once the Daily Change is back inside its percent. A Level waits while Last sits on its price. | code | test_rearm_takes_last_now, test_a_repeat_rearms_after_15_minutes, test_a_day_rearms_back_inside |
| A9 | A fire marks the alert fired and writes one Idea log line (kind `alert`) with Last, in one transaction, then sends one desk message: a toast on the desk and a Push under the key `idea-alert:{id}:{fires}`. | | test_a_fire_logs_and_emits_once |
| A10 | **Alert on my plan** arms a Once Level alert at each Plan price Last is not on: the zone edge nearer Last (none while In zone), the stop, and each Target. Each is labelled Entry zone, Stop, T1… A price that already has an armed Level alert on the Idea is skipped. With no Plan price it does nothing. | | test_plan_alerts_skip_prices_already_watched |
| A11 | A note is optional, up to 120 characters, and goes out with the Push. | code | test_alert_note_is_trimmed |

Texts, one line each, the note on its own line under it:

| Kind | Text |
|---|---|
| Level | `🔔 ZRO above 2.20 · T1 · Last 2.2034` |
| Move | `🔔 ZRO moved +5.02% from 2.15 (alert ±5%) · Last 2.2579`. Up shows `+5%`, down `−5%`, either `±5%`. |
| Day | `🔔 ZRO Daily Change +10.4% (alert +10%) · Last 2.2` |
| Met at start | the line ends `· met when the desk started` |

Prices are the ones stored, with thousands separators. The log line is the same text without the bell.
