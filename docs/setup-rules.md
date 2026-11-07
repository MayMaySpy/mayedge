# Setup rules

A **Setup** is a fact about a market's positioning or range, read on closed hours and closed days, that may be worth a swing trade. The **Setups** board on Scan lists them. Nothing on it toasts or pushes ([ADR 0026](adr/0026-a-setup-is-listed-not-raised.md)). Like an alert row, a Setup row states what the numbers show and does not name what it means ([ADR 0013](adr/0013-an-alert-is-a-fact-and-a-toast-is-a-coincidence.md)).

Every Setup is written to the desk database when it is first listed, with its facts and the price then, so it can be scored later at swing horizons.

Knobs are keys in the `setups:` block of `backend/config/alerts.yaml`. "code" means the number is not a knob yet. Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here.

## Gate and refresh

| | Rule | Knob | Pinned by |
|---|---|---|---|
| G1 | Only liquid perps are read (alert-rules G2: $1M of 24h volume, spread at most 40 bps). A Held market is not let through: the board is for finding trades. | `liquidity.*` | `test_a_thin_market_is_not_read` |
| G2 | The board is first built five minutes after the desk starts, once the daily bars are in, and then one minute after every UTC hour closes. Between rebuilds it does not change. | code | `test_the_board_is_rebuilt_once_an_hour` |
| G3 | Each Setup has a size: how many times its threshold it reached. The board lists the 20 largest, largest first. | 20 is code | `test_the_board_lists_the_largest` |

## Setups

| | Setup | Listed when | Facts | Direction | Knob | Pinned by |
|---|---|---|---|---|---|---|
| X1 | **Open interest without price** | Open interest has changed by at least 5% over the last 24 hours, and price by no more than a third of that, either way. | OI 24h %, price 24h %, funding sigma when the market is on the funding strip | none | `oi_pct`, `oi_over_price` | `test_open_interest_moving_without_price` |
| X2 | **Funding stretched** | Over the last 72 settled funding prints, at least 90% have the same sign, and their mean is at least 3× the market's median absolute print over the 30 days before them. Needs all 72 and at least 7 of those days. | 72h mean %/h, same-sign share, multiple of the 30-day median, which side pays | none | `funding_hours`, `funding_agree`, `funding_x` | `test_funding_stretched_for_three_days` |
| X3 | **Against the board** | BTC is down at least 1% over 24 hours and the market is at least 5 points better than BTC, or BTC is up at least 1% and the market is at least 5 points worse. The venue's 24h changes. | market 24h %, BTC 24h % | up when it holds, down when it lags | `board_pct`, `gap_pct` | `test_a_market_against_the_board` |
| X4 | **Coiled at a level** | The mean range of the last 3 completed UTC days is at most half the mean range of the 30 completed days before them, and the last trade is within 2% of the Week high or Week low (alert-rules W1). | range ratio, level, distance | none: the level says which | `coil_days`, `coil_ratio`, `coil_near_pct` | `test_a_quiet_range_under_a_week_high` |
| X5 | **Reclaim** | Yesterday's UTC day traded through the Week low of the 7 days before it and closed back above it, or through that Week high and closed back under it. | the level, yesterday's low or high and close | up from a low, down from a high | code | `test_a_failed_break_of_the_week_low` |
| X6 | **Liquidation flush** | In the last 4 hours, one side's liquidations reached at least 50 bps of open interest, and open interest fell at least 3% over those hours. | liquidated USD and bps, the forced side, OI 4h % | none | `flush_bps`, `flush_oi_pct` | `test_a_flush_of_one_side` |

A market can be listed for more than one Setup. Each is its own row.

Sizes: X1 is the OI change over 5%. X2 is the multiple over 3. X3 is the gap over 5 points. X4 is half over the range ratio. X5 is 1. X6 is the bps over 50.

## Record

| | Rule | Knob | Pinned by |
|---|---|---|---|
| R1 | A Setup is written when a market is first listed for it, with its facts, size, direction, and the last trade then. | | `test_a_new_setup_is_written_once` |
| R2 | A market still listed for the same Setup at the next rebuild is the same row: its last-seen time moves, nothing else. One that drops off and comes back is a new row. | | `test_a_setup_that_comes_back_is_a_new_row` |
| R3 | Rows are kept 365 days. | code | `test_setup_rows_are_kept_a_year` |

## Open

1. **No Setup is scored yet.** The record is there so it can be: the next 4 hours, 24 hours and 3 days from the price it was listed at.
2. **Taker flow is not read.** The desk drops trade frames for markets that are not on screen before it parses them, to keep the loop quiet. Price against net buying needs them parsed.
3. **X3 reads the venue's rolling 24h change.** A Broad move that started 30 hours ago is half out of it.
4. **X1 and X6 read stored open interest.** A market whose samples have a gap over the window has no OI change and is not listed.
