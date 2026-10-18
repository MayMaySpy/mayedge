# Alert rules

Every alert the desk can raise, the funding strip, and the two Scan boards. Change a rule here first, then the knob, the code and the test that pins it, in one commit ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)).

Knobs are keys in `backend/config/alerts.yaml`. "code" means the number is not a knob yet. Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here.

An alert is a fact, shown fast, for the operator to act on by feel. No row says what it means ([ADR 0013](adr/0013-an-alert-is-a-fact-and-a-toast-is-a-coincidence.md)).

Last checked against the code: 2026-10-12.

## Gate

| | Rule | Knob | Pinned by |
|---|---|---|---|
| G1 | Only perps alert or reach a Scan board. | code | |
| G2 | A market is liquid while its 24h volume is at least $1M and its spread is at most 40 bps. With no two-sided quote, volume alone decides. A market that is not liquid raises nothing and is on no board. | `liquidity.min_24h_usd`, `liquidity.max_spread_bps` | `test_a_thin_market_never_alerts`, `test_a_thin_market_is_on_no_board` |
| G3 | A **Held market** passes G2 whatever its volume. | code | `test_a_thin_market_alerts_once_it_is_held` |

## Spikes

A **Spike** is a minute at least N times the biggest minute of the last hour ([ADR 0014](adr/0014-a-spike-is-a-multiple-of-the-hours-biggest-minute.md)). Being the biggest minute of the hour is not enough: every market manages that about once an hour.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| K1 | The hour is the last 60 closed one-minute bars for price and volume, and the last 60 one-minute samples for open interest. The minute being judged is never part of it. | `spike.window_min` | `test_the_minute_being_judged_is_not_in_its_own_hour` |
| K2 | Price spikes when the last trade is at least 0.25% from where it was 1m ago, and that move is at least 2× the biggest close-to-close minute of the hour. | `spike.price_x`, `spike.min_move_pct` | `test_a_price_spike_doubles_the_hours_biggest_minute`, `test_a_big_minute_in_a_wild_hour_is_no_spike` |
| K3 | Volume spikes when the forming minute has traded at least $50k and at least 3× the biggest minute of the hour. | `spike.volume_x`, `spike.min_volume_usd` | `test_a_volume_spike_triples_the_hours_biggest_minute` |
| K4 | Open interest spikes when it has changed over the last 1m by at least $250k and 0.3% of itself, and at least 2× the biggest one-minute change of the hour. | `spike.oi_x`, `spike.min_oi_usd`, `spike.min_oi_pct` | `test_an_oi_spike_doubles_the_hours_biggest_change` |
| K5 | While a **Broad move** is on, the price of a market going the same way is judged on its **Excess move**. A market that moves less than the board does not spike. | code | `test_a_market_must_beat_the_board` |
| K6 | Price and volume need a full hour of bars. The desk loads 240 per perp at boot. Open interest loads its hour from the desk database. | `baseline.bars_1m` | `test_no_spike_without_an_hour_behind_it` |
| K7 | A spike needs no re-arm of its own. Once its minute closes it is the hour's biggest, and the next one has to beat it. | | `test_the_next_spike_has_to_beat_this_one` |

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
| B3 | Board fires when the Broad move is at least 0.5%. It is one row, named Market. Opening it opens BTC. | `board.median_pct` | `test_a_board_move_is_one_row` |

## Held

| | Rule | Knob | Pinned by |
|---|---|---|---|
| H1 | A **Held market** has a **Position** or a working order on it. | code | `test_a_position_or_a_working_order_makes_a_market_held` |
| H2 | Near liquidation fires when mark is within 10% of a Position's **Liquidation price**. The direction is toward that price. | `held.liq_distance_pct` | `test_mark_near_the_liquidation_price` |
| H3 | A row on a Held market says which side is held, and whether a move runs with it or against it. | code | `test_a_row_on_a_held_market_is_urgent` |

## Rows

A row is one alert in the panel. Each rule that fires has a size: how many times its threshold it reached.

| | Rule | Knob | Pinned by |
|---|---|---|---|
| R1 | A row opens when a rule fires on a market with no row still taking updates, and the cap has room (R6). | | |
| R2 | A row takes updates for 2 minutes from its start. Rules that fire on that market in that time join it, each kept at its largest. It is sent again when its size (to 0.1), its headline, its count of rules or its severity changes. Then it is final. | `rows.merge_s` | `test_rules_within_two_minutes_are_one_row`, `test_an_unchanged_row_is_not_sent_again`, `test_a_final_row_is_not_rewritten` |
| R3 | A row is Urgent when two or more spikes are on it, when Liquidations, Board or Near liquidation is on it, or when the market is Held. Otherwise it is Notable. | code | `test_two_spikes_at_once_are_urgent`, `test_a_row_on_a_held_market_is_urgent` |
| R4 | Liquidations, Board and Near liquidation are states that go on firing. Each raises one row when it starts. While it keeps firing it raises another only at half again its largest size so far. It starts afresh after 3 minutes without firing. | `rows.quiet_s`; half again is code | `test_a_standing_state_is_one_row`, `test_a_state_that_grows_by_half_is_a_new_row` |
| R5 | Every market row carries the 1m price move. It carries the minute's volume and its change in open interest when each is over its floor and at least the hour's biggest, whether or not it spiked. | code | `test_a_row_carries_what_the_tape_showed` |
| R6 | At most 6 new rows in any minute, across all markets. The seventh is dropped, not held. | `rows.max_new_per_min` | `test_rate_cap` |
| R7 | A row says when the price is at the day's high or low: within 2 bps of the venue's 24h high or low, or past it. | 2 bps is code | `test_a_row_says_when_price_is_at_the_days_high` |
| R8 | A row says when the market is on the funding strip (F1). | | `test_a_row_says_when_funding_is_extreme` |

## Funding

| | Rule | Knob | Pinned by |
|---|---|---|---|
| F1 | Funding is extreme when the hourly rate is at least 3 sigma from the market's own 24h median. | `funding.sigma`, `funding.sigma_floor` | `test_funding_far_from_its_own_day_is_extreme` |
| F2 | The strip above the alerts lists every liquid or Held market whose funding is extreme now, furthest first. It raises no row and no toast. | | `test_the_strip_lists_what_is_extreme_now` |
| F3 | The desk writes each perp's funding rate at every UTC minute close and keeps 3 days. At boot it loads the last 24h, so a restart does not forget what is normal. | `funding.retention_days` | `test_funding_survives_a_restart` |

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
| S1 | Every row is written to the desk database when it opens, with its rules and what the tape showed, and again when it changes. | `outcomes.retention_days` | `test_a_row_is_written_with_its_facts` |
| S2 | **Left** and **Against** are read from the highs and lows of the 15 one-minute bars after the bar the row fired in, from the price it fired at ([ADR 0012](adr/0012-an-alert-is-scored-from-the-price-it-fired-at.md)). | `outcomes.horizon_min` | `test_left_and_against_start_at_the_alert`, `test_the_alert_bar_is_not_counted` |
| S3 | A row is **Opened** when the operator opens its Market from the panel. | | `test_opening_a_row_is_recorded_once` |
| S4 | A row with no direction, and the Market row, are written and can be Opened. They have no Left or Against. | code | `test_the_market_row_is_written_and_not_measured` |
| S5 | `GET /api/alerts/stats?hours=N` gives, per rule: rows, median Left, median Against, and how many were Opened. The panel shows 24h. | | `test_stats_are_per_rule` |

## Panel

| | Rule | Where |
|---|---|---|
| P1 | Show is All or Urgent. All is the default. | `AlertsPanel.tsx` |
| P2 | Favorites only hides every other market, except a Held market. A muted market is hidden until unmuted. The Market row is always shown. | `shownAlerts` in `alertFormat.ts` |
| P3 | The list is the last 80 rows that pass P1 and P2, newest first. | `MAX_ROWS` |
| P4 | An Urgent row under 8s old raises a toast, once per row, two at a time. | `TOAST_MAX`, `TOAST_MAX_AGE_MS` |
| P5 | A row reads as its facts: what spiked and by how much, then what the tape showed. | `alertFormat.ts` |
| P6 | The funding strip (F2) sits above the list. A market on it opens when clicked. | `AlertsPanel.tsx` |

## Open

1. **The multiples are from one day.** (K2 to K4) Volume and price were counted on 8.3 hours of 11 Oct 2026, a Sunday, and open interest on three days: about 220 spikes a day across 43 liquid perps. Read S5 after a week and move them.
2. **Price is judged on a rolling minute against bar-to-bar minutes.** (K2) A move that straddles two bars is seen whole now and in halves in the hour behind it, so price is a little easier to spike than the wording says.
3. **A Broad move knows no asset class.** (B2) Ten equity perps moving at the US open are a Broad move, the same as ten crypto perps.
4. **Volume has no side.** (K3) The tape's buy and sell split is not used.
5. **The cap drops by arrival.** (R6) In a busy minute the seventh row is lost even if it is the largest. A board-wide volume surge can fill it.
6. **Premium still forgets normal at a restart.** (A3) Funding is stored. Premium is not.
7. **Left and Against stop at 15 minutes.** (S2)
8. **Tones are listed, not scored.** (T1) Measured once on 9 days of 30m bars: blue was followed by +0.05% over the next 30m against +0.01% for any bar, orange by a small move the wrong way.
9. **Working orders make a market Held.** (H1, R3) Every spike on a market with a resting order far from the price raises a toast.
10. **Funding is extreme against its own day only.** (F1) A market whose funding has been stretched all day is not on the strip.
11. **A volume spike points nowhere.** (S4) It has no Left or Against, and it is the most common row. Only Opened says whether those rows are worth raising.
12. **Every Board row is a toast.** (B3, R3) Replaying 6.4 hours of 11 Oct 2026 raised ten, most of them between 0.5% and 0.6%.
