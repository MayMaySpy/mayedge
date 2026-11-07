# Alert rules

Every alert the desk can raise, the funding strip, and the two Scan boards. Change a rule here first, then the knob, the code and the test that pins it, in one commit ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)).

Knobs are keys in `backend/config/alerts.yaml`. "code" means the number is not a knob yet. Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here.

An alert is a fact, shown fast, for the operator to act on by feel. No row says what it means ([ADR 0013](adr/0013-an-alert-is-a-fact-and-a-toast-is-a-coincidence.md)).

Last checked against the code: 2026-11-07.

Price leads ([ADR 0027](adr/0027-an-alert-is-a-price-move.md)). Volume and open interest are said on a row; they never raise one. The Board is a line above the list, not rows.

## Gate

| | Rule | Knob | Pinned by |
|---|---|---|---|
| G1 | Only perps alert or reach a Scan board. | code | |
| G2 | A market is liquid while its 24h volume is at least $1M and its spread is at most 40 bps. With no two-sided quote, volume alone decides. A market that is not liquid raises nothing and is on no board. | `liquidity.min_24h_usd`, `liquidity.max_spread_bps` | `test_a_thin_market_never_alerts`, `test_a_thin_market_is_on_no_board` |
| G3 | A **Held market** passes G2 and G4 whatever its volume. | code | `test_a_thin_market_alerts_once_it_is_held` |
| G4 | A market alerts only while at least 80% of its last 240 one-minute bars traded. A market that sat still all morning is not moving 99 times its usual when it prints once. | `move.live_share` | `test_a_dead_tape_never_alerts` |

## Moves

A **Move** is the price going much further than this market usually goes in the same time. It is the only rule that raises a row on a market's own tape. Volume and open interest are said on it, never raised alone ([ADR 0027](adr/0027-an-alert-is-a-price-move.md)).

| | Rule | Knob | Pinned by |
|---|---|---|---|
| M1 | A Move is judged over 1, 5 and 15 minutes: the last trade against the close of the one-minute bar 1, 5 or 15 bars back. | | `test_a_move_is_judged_over_one_five_and_fifteen_minutes` |
| M2 | Its **Usual move** for each span is the median size of that span's move across the last 240 closed one-minute bars, step by step. It needs all 240. | `move.usual_bars` | `test_no_move_without_a_usual_behind_it` |
| M3 | A span fires when its move is at least 12 times its Usual move and at least its floor: 1% over 1m, 1.5% over 5m, 2% over 15m. The row leads with the span furthest past its threshold. | `move.x`, `move.floor_1m_pct`, `move.floor_5m_pct`, `move.floor_15m_pct` | `test_a_move_is_twelve_times_its_usual`, `test_a_big_usual_needs_a_bigger_move`, `test_a_small_move_on_a_still_tape_is_no_move` |
| M4 | While a **Broad move** is on, a market going the same way is judged on its **Excess move** over the same span: its move less the board's median move over that span. A market that moves less than the board does not fire. | code | `test_a_market_must_beat_the_board` |
| M5 | A Move is a state. It raises one row when it starts. While it keeps firing, it raises another only at half again its largest size. It starts afresh after 15 minutes without firing. | `move.quiet_s`; half again is code | `test_a_move_that_keeps_going_is_one_row`, `test_a_move_that_grows_by_half_is_a_new_row` |
| M6 | A Move row says the volume over its span as a multiple of this market's mean for that span, when it is at least 2×. It says the change in open interest over its span when the desk has it. | 2× is code | `test_a_move_says_its_volume_and_open_interest` |
| M7 | A minute of volume or open interest with no Move raises nothing. | | `test_volume_alone_raises_nothing`, `test_open_interest_alone_raises_nothing` |

## Week and quarter

A **Week high**, **Week low**, **Quarter high** or **Quarter low** is a level the price runs into. The day being lived is not part of the level ([ADR 0022](adr/0022-a-week-high-excludes-today.md)).

| | Rule | Knob | Pinned by |
|---|---|---|---|
| W1 | The week is the 7 completed UTC days before today. The quarter is the 90. Today is in neither. A window with fewer daily bars has no level. | `range.week_days`, `range.quarter_days` | `test_a_short_history_has_no_week_high`, `test_today_is_not_part_of_the_week` |
| W2 | A level breaks when a one-minute bar closes past it and the bar before it did not. Touching it is not a break. | | `test_a_close_through_the_week_high_breaks_it`, `test_a_close_through_the_quarter_high_breaks_it`, `test_touching_a_level_is_no_break` |
| W3 | Each level breaks at most once a UTC day per market. A market that closes back and through again the same day raises nothing new. | | `test_a_level_breaks_once_a_day` |

## Liquidations

| | Rule | Knob | Pinned by |
|---|---|---|---|
| L1 | Liquidations fire when at least $100k is liquidated on a market inside 120s and that is at least 20 bps of its open interest. | `liquidations.min_usd`, `liquidations.window_s`, `liquidations.oi_bps` | `test_liquidations_are_sized_against_open_interest` |
| L2 | The direction is down when at least half the fills are **Long liquidations**, else up. | code | `test_liquidations_are_sized_against_open_interest` |

## Board

| | Rule | Knob | Pinned by |
|---|---|---|---|
| B1 | A mover is a liquid perp beyond 0.3% over 5m. | `board.move_pct` | |
| B2 | A **Broad move** is on when at least 10 perps are movers and at least 80% of the movers go the same way. Its size is the median 5m move of that side. | `board.min_movers`, `board.agree` | `test_a_board_move_is_counted_among_the_movers`, `test_a_split_board_is_no_broad_move` |
| B3 | While the Broad move is at least 0.8%, the Board line above the list says its side, its size and how many movers share it. It raises no row and no toast. Clicking it opens BTC. | `board.median_pct` | `test_a_board_move_is_a_line_not_a_row` |

## Held

| | Rule | Knob | Pinned by |
|---|---|---|---|
| H1 | A **Held market** has a **Position** on it, or a working order within 2% of filling. A limit is measured from the last trade, a Stop or Take Profit from mark to its trigger, and an order already through is 0. An order with no price to measure from counts as near. | `held.order_near_pct` | `test_a_position_or_a_working_order_makes_a_market_held`, `test_a_far_order_does_not_make_a_market_held` |
| H2 | Near liquidation fires when mark is within 10% of a Position's **Liquidation price**. The direction is toward that price. | `held.liq_distance_pct` | `test_mark_near_the_liquidation_price` |
| H3 | A row on a Held market says which side is held, and whether the move runs with it or against it. | code | `test_a_move_against_a_held_side_is_urgent` |

## Rows

A row is one alert in the panel. Each rule that fires has a size: how many times its threshold it reached.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| R1 | A row opens when a rule fires on a market with no row still taking updates, and the cap has room (R6). | | |
| R2 | A row takes updates for 2 minutes from its start. Rules that fire on that market in that time join it, each kept at its largest. It is sent again when its size (to 0.1), its headline, its count of rules or its severity changes. Then it is final. | `rows.merge_s` | `test_rules_within_two_minutes_are_one_row`, `test_an_unchanged_row_is_not_sent_again`, `test_a_final_row_is_not_rewritten` |
| R3 | A row is Urgent when Liquidations or Near liquidation is on it, when it runs against a held Position, or when a working order is the only thing held. A row that runs with a held Position is Notable, as is every row on a market not held ([ADR 0027](adr/0027-an-alert-is-a-price-move.md)). | code | `test_a_move_against_a_held_side_is_urgent`, `test_a_move_with_a_held_side_is_notable`, `test_a_move_near_a_working_order_is_urgent` |
| R4 | Liquidations and Near liquidation are states that go on firing. Each raises one row when it starts. While it keeps firing it raises another only at half again its largest size so far. It starts afresh after 3 minutes without firing. A Move does the same on its own clock (M5). | `rows.quiet_s`; half again is code | `test_a_standing_state_is_one_row`, `test_a_state_that_grows_by_half_is_a_new_row` |
| R5 | A row that is not a Move carries the 1m price move. | code | `test_a_row_carries_the_minute` |
| R6 | At most 6 new rows in any minute, across all markets. The seventh is dropped, not held. | `rows.max_new_per_min` | `test_rate_cap` |
| R7 | A row says when the price is at the day's high or low: within 2 bps of the venue's 24h high or low, or past it. | 2 bps is code | `test_a_row_says_when_price_is_at_the_days_high` |
| R8 | A row says when the market is on the funding strip (F1). | | `test_a_row_says_when_funding_is_extreme` |

## Funding

| | Rule | Knob | Pinned by |
|---|---|---|---|
| F1 | Funding is extreme when the hourly rate is at least 3 sigma from the market's own 24h median. | `funding.sigma`, `funding.sigma_floor` | `test_funding_far_from_its_own_day_is_extreme` |
| F2 | The strip above the alerts lists every liquid or Held market whose funding is extreme now, furthest first. It raises no row and no toast. | | `test_the_strip_lists_what_is_extreme_now` |
| F3 | The desk writes each perp's **Funding estimate** at every UTC minute close and keeps 30 days. Settled **Funding prints** are kept for the life of the desk. At boot it loads the last 24h, so a restart does not forget what is normal. | `funding.retention_days` | `test_funding_survives_a_restart` |

## Scan boards

Nothing on a board alerts.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| A1 | Activity lists every liquid perp, sent every 5s when it has changed. | 5s is code | `test_activity_lists_every_liquid_perp` |
| A2 | Its columns: the 5m move and its share of the **Day range**, the range never taken as under 3%. The volume multiple: USD in the last five 1m bars over five of this market's mean bar of the last 240, the mean never under the 24h mean. The 5m change in open interest, in percent and USD. Funding and premium, each with its sigmas from its own 24h median. | `activity.range_floor_pct`, `baseline.bars_1m`, `baseline.level_window_min` | `test_activity_lists_every_liquid_perp`, `test_forming_bar_rvol`, `test_structural_level_scores_near_zero` |
| A3 | Volume needs 30 one-minute bars. A sigma needs 30 minutes of samples. Until then the cell is blank. Premium starts empty at every restart. | `baseline.min_bars`, `baseline.level_min_samples` | `test_needs_min_bars`, `test_silent_until_min_samples` |
| T1 | Tones lists the liquid perps whose last closed bar on a **Tone timeframe** is blue or orange. | Board: at most two, default 30m and 4h | `test_the_board_lists_the_last_closed_bar`, `test_default_is_30m_and_4h`, `test_rejects_a_third` |
| T2 | Blue: the bar before closed under the lower line. This bar closed back above it, under the upper line, and above its own open. | `mayrekt.py`, [ADR 0009](adr/0009-mayrekt-runs-on-the-bars-on-screen.md) | `test_later_bar_closes_blue_once` |
| T3 | Orange: two bars back closed above the upper line. This bar closed under its open, under the last close, under the last low and under the upper line, and above the low of the three bars before it. | `mayrekt.py` | `test_orange_and_other_tones` |
| T4 | A bar is closed when the next bar arrives, or 15s after its end. The forming bar is never listed. A series needs 50 bars. | code | `test_forming_update_does_not_alert`, `test_clock_closes_a_quiet_bar_after_grace`, `test_short_history_does_not_alert` |
| T5 | A row leaves when the next bar on that timeframe closes any other tone. | code | `test_the_next_close_clears_the_row` |

Sigma is the larger of 1.4826 × MAD and the 90th-percentile deviation over 1.645, never under 0.002 for funding or 0.05% for premium. A bar has one tone: breakout, breakdown, orange and `bon` outrank blue, and only breakout and breakdown outrank orange.

## Record

| | Rule | Knob | Pinned by |
|---|---|---|---|
| S1 | Every row is written to the desk database when it opens, with its rules and what the tape showed, and again when it changes. Rows are kept for `rows.log_retention_days` (90). `outcomes.retention_days` (30) is unchanged and does not purge these rows. | `rows.log_retention_days` | `test_a_row_is_written_with_its_facts`, `test_row_retention_is_separate_from_outcomes` |
| S2 | **Left** and **Against** are read from the highs and lows of the 15 one-minute bars after the bar the row fired in, from the price it fired at ([ADR 0012](adr/0012-an-alert-is-scored-from-the-price-it-fired-at.md)). | `outcomes.horizon_min` | `test_left_and_against_start_at_the_alert`, `test_the_alert_bar_is_not_counted` |
| S3 | A row is **Opened** when the operator opens its Market from the panel. | | `test_opening_a_row_is_recorded_once` |
| S4 | A row with no direction is written and can be Opened. It has no Left or Against. Board rows from before ADR 0027 stay in the record. | code | `test_the_market_row_is_written_and_not_measured` |
| S5 | `GET /api/alerts/stats?hours=N&by=` gives, per group: rows, how many were measured, median Left and Against, the 25th and 75th of each, the share where Left beat Against, and how many were Opened (count and rate). `by` is `rule` (the default, which the 24h panel reads), `rule_severity`, `rule_direction`, `held`, `hour`, or `symbol`. Hours run out to 90 days. | | `test_stats_are_per_rule`, `test_stats_group_and_percentiles` |
| S6 | The Record dialog shows 7, 30 and 90 days. A group with fewer than 20 rows says so and is not colored. | | `AlertRecordDialog` |
| S7 | A what-if only **tightens** a mapped knob. It keeps rows whose stored fact would still clear the new value, and shows that next to the baseline. A looser value would have raised rows that were never written, so the desk returns the baseline unchanged with `looser=true` and says so. An unknown knob is rejected. The dialog does not write `alerts.yaml`; it shows the line to change. | | `test_whatif_tightens_each_mapped_knob`, `test_a_looser_knob_returns_the_baseline`, `test_an_unknown_knob_is_rejected` |

## Panel

| | Rule | Where |
|---|---|---|
| P1 | Show is All or Urgent. All is the default. | `AlertsPanel.tsx` |
| P2 | Favorites only hides every other market, except a Held market. A muted market is hidden until unmuted. The Market row is always shown. | `shownAlerts` in `alertFormat.ts` |
| P3 | The list is the last 80 rows that pass P1 and P2, newest first. | `MAX_ROWS` |
| P4 | An Urgent row under 8s old raises a toast, once per row, two at a time. | `TOAST_MAX`, `TOAST_MAX_AGE_MS` |
| P7 | The Board line (B3) sits above the funding strip. With no Broad move it says so. | `AlertsPanel.tsx` |
| P5 | A row reads in plain words, price first: the move, its span and the price, then how many times its usual, then volume, open interest, the day's high or low and the held side. | `alertFormat.ts` |
| P6 | The funding strip (F2) sits above the list. A market on it opens when clicked. | `AlertsPanel.tsx` |

## Open

1. **Moves were set on short history.** (M3) The desk serves 500 bars a span. On 7 Nov 2026, over 47 liquid perps: 15m bars across 5 days at 12× and a 1.5% floor gave about 9 rows a day, and price went further the alert's way in the next 15 minutes 62% of the time. 5m bars across 41 hours gave about 14 a day, a coin flip. 1m bars across 8 hours of a Saturday gave about 30 a day, and they went back. Read the record after a week.
2. **A span is up to a minute long.** (M1) The last trade is judged against a closed bar, so a 1m Move runs from 0 to 60 seconds and a 15m Move from 14 to 15 minutes. The Usual move is measured bar to bar.
3. **A Broad move knows no asset class.** (B2) Ten equity perps moving at the US open are a Broad move, the same as ten crypto perps.
4. **Volume has no side.** (M6) The tape's buy and sell split is not used.
5. **The cap drops by arrival.** (R6) In a busy minute the seventh row is lost even if it is the largest.
6. **Premium still forgets normal at a restart.** (A3) Funding is stored. Premium is not.
7. **Left and Against stop at 15 minutes.** (S2)
8. **Tones are listed, not scored.** (T1) Measured once on 9 days of 30m bars: blue was followed by +0.05% over the next 30m against +0.01% for any bar, orange by a small move the wrong way.
9. **A near order is measured on the price, not the book.** (H1) A thin market whose book sits far from its last trade can make a far order look near, or a near one far.
10. **Funding is extreme against its own day only.** (F1) A market whose funding has been stretched all day is not on the strip.
11. **Why the spikes went.** In the 30 days to 7 Nov 2026 the desk wrote 6,642 rows and 358 were Opened. Volume was 34% of them, 45% of those with the price moving under 0.1%. Board was 1,307 rows, 50 to 80 a weekday. No rule did better than a coin flip in the 15 minutes after it.
