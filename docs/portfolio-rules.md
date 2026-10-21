# Portfolio rules

What the **Portfolio** shows and how each number is worked out. The scope and the build order are in [plans/2026-10-portfolio-scope.md](plans/2026-10-portfolio-scope.md). Change a rule here first, then the code and the test that pins it, in one commit ([ADR 0011](adr/0011-alert-rules-are-written-down-before-they-are-coded.md)).

## What the venue says

Checked against mainnet on 2026-10-20 through a temporary read-only desk route, now removed. Pinned by `backend/tests/test_portfolio_venue.py` on `backend/tests/fixtures/portfolio_raw.json`. That fixture is the real answer's shape, with the account's own figures scaled by 0.5, its index replaced and its address dropped.

### The `pnl` endpoint is the backbone

`GET /api/v1/pnl?by=index&value=<account_index>&resolution=<1h|1d>&start_timestamp=…&end_timestamp=…&count_back=…`

| | What it is |
|---|---|
| V1 | Every money field is **cumulative since the account opened**, not per bucket: `trade_pnl`, `trade_spot_pnl`, `pool_pnl`, `staking_pnl` and each kind's `*_inflow` and `*_outflow`. Only `volume` is per bucket. |
| V2 | The default answer is **PnL net of Flows**. With `ignore_transfers=true`, the same fields are each Holding kind's **value**. |
| V3 | For every kind, value less cumulative PnL equals cumulative inflow less outflow, to within a dollar: Perps `trade_pnl` / `inflow`, `outflow`; Spot `trade_spot_pnl` / `spot_inflow`, `spot_outflow`; LLP `pool_pnl` / `pool_inflow`, `pool_outflow`; Staking `staking_pnl` / `staking_inflow`, `staking_outflow`. |
| V4 | A kind's change over a span is its cumulative PnL at the end less at the start. On 2026-10-20, today's Perps change from the venue matched that day's closed Round trips in the Journal to the cent. |
| V5 | Bucket timestamps are **seconds**, whichever unit is sent. Buckets sit on the hour (`1h`) or on UTC midnight (`1d`). The last bucket is partial and is stamped with the time of the request. |
| V6 | `staked_lit` is in the SDK model but **not** in the live answer. `pool_total_shares` is present and was 0 here. |
| V7 | `1h` and `1d` work. Other resolutions are untested. |

### The account

`GET /api/v1/account?by=index&value=<account_index>`

| | What it is |
|---|---|
| A1 | `total_asset_value` equals `collateral`, which is USDC's `margin_balance`. That is the Perps value (V2 agrees). On 2026-10-20 USDC's spot `balance` was 0; on 2026-10-21 the venue answered `balance` equal to `margin_balance` (1,014.01 both), the same money twice, and the Spot value was still ETH alone. **USDC is never counted as Spot: it is the Perps collateral, and the Perps card names it.** |
| A2 | A spot asset used as collateral (ETH, `margin_mode: enabled`) sits in `margin_balance`, not `balance`. `cross_asset_value` adds it with a haircut; `total_asset_value` leaves it out. It counts once, as Spot. |
| A3 | `shares[]` lists pool shares: `public_pool_index`, `shares_amount`, `principal_amount`. `entry_usdc` was `"0"` and `entry_timestamp` was `0`: unset, so neither is shown. |
| A4 | `pending_unlocks` was empty, so its timestamp unit is not checked. Treat a value above `10^12` as ms, the same as the journal does. |
| A5 | The desk's account WS handlers do not read `shares` or `pending_unlocks`, and whether those feeds carry them is unchecked. Read them from this REST call. |

### Pools

| | What it is |
|---|---|
| P1 | `publicPoolsMetadata` lists pools **downward from `index`**: `index=0` returns nothing. Start at `281474976710655` (2^48 − 1). |
| P2 | **LLP** is pool `281474976710654`, `account_type` 3, named "Lighter Liquidity Provider". |
| P3 | **LIT staking** is pool `281474976624800`, `account_type` 4. It appears only with `filter=stake`. It holds only LIT, so its USD `total_asset_value` is 0 and `total_spot_value` carries its value. |
| P4 | Reading a pool as an account (`account?by=index&value=<pool>`) gives `pool_info`: `total_shares`, `annual_percentage_yield`, and daily `share_prices` in **USD per share** (seconds). `daily_returns` is the share price's own day-on-day move. |
| P5 | LIT behind a staking share = `shares_amount × pool LIT ÷ total_shares`. `principal_amount` is the LIT put in, so staked LIT exceeds it by the yield earned. |

## What this means for the build

- Value per kind, its history, and the Day change all come from the `pnl` endpoint (V1–V4). The desk does not rebuild any of them from prices, so double counting (A1, A2) cannot come in through the desk's own maths.
- The account and pool reads add only what `pnl` lacks: quantities (ETH, staked LIT), share counts, APY, unlocks.
- The **Day open** is UTC midnight, so every day is a venue `1d` bucket; today so far adds the `1h` buckets since 00:00 UTC.
- The mismatch check in the scope becomes V3: if value less PnL drifts from net Flows by more than a dollar, a field changed meaning.

## Now (`GET /api/portfolio`)

| | Rule | Pinned by |
|---|---|---|
| N1 | The **Day open** is 00:00 UTC today. The desk never uses local time. A caller may send another start as `open` (ms): the page's **24h** sends 24 hours back. The desk rounds it down to the hour, because buckets are hourly (V5). An `open` in the future, or more than 30 days back, is refused. | test_open_rounds_down_to_the_hour, test_open_out_of_range_is_refused |
| N2 | A kind's **value now** is the last bucket of the `ignore_transfers` series (V2, V5). Its **value at the open** is the bucket stamped at the open hour, or the latest one before it. With none before it, the account did not exist yet and the value at open is 0. | test_values_now_and_at_open |
| N3 | A kind's **Day change** is its cumulative PnL now less at the open (V1, V4). Its **Flows** today are its net inflow now less at the open. | test_day_change_is_cumulative_pnl_now_less_at_open |
| N4 | The Portfolio total is the sum of Perps, Spot, LLP and Staking. **Day change %** is the Day change ÷ (value at open + Flows today). With that base at 0 or below, there is no %. | test_day_change_pct_counts_todays_flows_in_the_base |
| N5 | **Mismatch**: on the latest **closed** bucket both series share (never the partial one: each request stamps its own "now", and a LIT or ETH move between the two reads as drift), a kind whose value less cumulative PnL drifts from its net Flows by more than $1 is listed with the drift (V3). The page says so. It does not hide it. | test_a_drift_over_a_dollar_is_a_mismatch, test_the_partial_bucket_never_reads_as_a_mismatch |
| N6 | **Holding detail** adds quantities to the totals; it never changes them. **Perps rows** are the quote collateral, USDC's live `margin_balance` at its index price, and the open uPnL from the live account (A1). Spot rows are the desk's live asset rows, USDC left out (A1). When the Spot value is more than $1 and more than 1% away from what its rows add up to, the answer carries that **Spot gap** and the Spot card names it: the venue counts an asset the desk does not list. Staking and LLP rows are the account's shares: units behind a share = `shares_amount × pool units ÷ total_shares` (P4, P5). Staked LIT is valued at the live LIT index price. LLP is valued at the pool's `total_asset_value ÷ total_shares`. Pending unlocks are listed with their date (A4). | test_staking_row_from_the_share_and_the_pool, test_usdc_is_never_a_spot_row, test_usdc_is_the_perps_collateral, test_perps_detail_names_the_collateral_and_the_open_upnl, test_spot_value_its_rows_leave_out_is_named |
| N10 | The Perps card shows the **Portfolio margin** under its rows, as buying power: the USDC cross portfolio (collateral with the open uPnL in it), plus each collateral asset's `margin_balance` × index × LTV, each part listed. It is the header's MARGIN figure, worked from the same terms, so the two never disagree. It is never added to Perps, to the total or to the Allocation: the same ETH is already in Spot at full value, and adding 70% of it again would count it twice. Only a detailed answer carries it. | test_the_margin_is_buying_power_beside_the_value, test_parts_add_up_to_the_portfolio_margin |
| N7 | One answer reads at most two `pnl` series, the account, and one pool account per share held. Each read takes the shared budget's read lane. An answer is reused for 30s per Day open. | test_the_answer_is_reused_for_30s |
| N8 | `detail=0` reads only the two `pnl` series: totals and kinds, no holding rows. A detailed answer from the last 30s serves a plain request too. | test_a_plain_answer_reads_only_the_pnl_series |
| N9 | The desk header shows **Today**: the total Day change and its %, since 00:00 UTC, from the plain answer (N8). It asks once a minute while the tab is visible, and again when the tab comes back. It shows nothing when trading is off, before the first answer, or when the last answer is more than 5 minutes old, so a stale figure is never shown as today's. Hovering lists each kind held with its Day change and value, the total, today's Flows when there are any, and each mismatch (N5). A mismatch also marks the figure with `!`. | `PortfolioToday` tests |

## History

| | Rule | Pinned by |
|---|---|---|
| H1 | The desk stores the venue's `pnl` buckets at `1h` and `1d`, each in both modes: **pnl** (default) and **values** (`ignore_transfers=true`). Only buckets on the hour (`1h`) or on UTC midnight (`1d`) are stored. The partial bucket stamped "now" never is (V5); the live answer (N2) covers it. A bucket the venue answers again replaces the stored one. | test_only_closed_buckets_are_stored, test_a_bucket_answered_again_replaces_the_stored_one |
| H2 | **Backfill** walks back from now in windows of 48 hourly or 30 daily buckets. It stops at a window where every bucket is zero in every field (before the account existed), when the venue answers `400` with code `22403` ("time range exceeds maximum allowed range for the specified resolution": older than it keeps at that resolution; on 2026-10-20 hourly went back about a week), or at the desk's own horizon: 90 days hourly, 2 years daily. Done is marked per resolution (`portfolio_backfilled_1h`, `portfolio_backfilled_1d`). Until then each sync carries on from the oldest stored bucket, so a backfill cut short is finished later rather than leaving a hole. | test_backfill_walks_back_until_the_account_did_not_exist, test_backfill_stops_at_the_venues_horizon, test_an_interrupted_backfill_carries_on_from_the_oldest_bucket |
| H3 | Once backfilled, a sync reads the last 3 hourly and the last 2 daily buckets in both modes. Syncs run 30s after boot, then every 5 minutes. Every read takes the background lane and waits for room. Nothing syncs when trading is off. | test_a_sync_after_the_backfill_reads_only_the_latest_buckets |
| H4 | **Value history** (`GET /api/portfolio/history?range=1d|7d|30d|90d|all`) is each kind's value at every stored bucket, plus the total. `1d` and `7d` are hourly; `30d`, `90d` and `all` are daily, because the venue keeps hourly buckets for only about a week (H2). | test_history_is_hourly_for_a_week_and_daily_beyond |
| H5 | A **Flow marker** is a bucket where a kind's cumulative net Flow moved by more than $1 since the bucket before. It carries the kind and the amount: positive in, negative out. The page draws it, so a deposit is never read as a gain. | test_a_flow_marker_is_a_move_in_net_flows |
| H6 | **Daily change** (`GET /api/portfolio/days?range=7d|30d|90d|all`) is each kind's Day change per **UTC day**, from one daily bucket to the next. Today runs from the bucket at 00:00 UTC (daily, or hourly while the daily one is not stored yet) to the last stored hourly bucket; the page shows the live Day change (N3) above it. A day missing either bucket is left out. | test_days_are_utc_days, test_today_runs_from_utc_midnight_to_the_last_hourly_bucket |

## Page (`/portfolio`)

| | Rule | Pinned by |
|---|---|---|
| W1 | The page reads over REST only: the detailed answer (N7) once a minute while visible, the history (H4) and the days (H6) when the range changes. It opens no desk socket. The header's **Portfolio** button and its **Today** open it in a new tab. | `PortfolioPage` tests |
| W2 | It leads with the Portfolio total and its change since the Day open. **Today** means since 00:00 UTC (N1); **24h** sends an open 24 hours back, rounded down to the hour. Flows since the open are shown beside the change, never inside it. Every time on the page is UTC and says so. | `leads with the total…`, `switches to the last 24 hours` |
| W3 | **Allocation** is one bar of the kinds held now, in the fixed order Perps, Spot, LLP, Staking, each in its own hue, labelled with $ and %. The hues are fixed per kind (`PORTFOLIO_KIND_COLORS`), never re-sorted by size, and validated for color-blind separation on the desk's dark panel. Green and red are not among them: on this desk they mean gain and loss. | `portfolio kinds` |
| W4 | **Value** draws one line per kind that held money at any point in the range, plus the total, on one axis in short dollars ($8k) that never goes below 0. Flows (H5) never sit on a line: each moment money moved is one chip in a lane under the plot, with a faint dashed guide up through it. A moment whose Flows cancel out (under $1 net) is a **move** between kinds (⇄), otherwise a **deposit** (↑) or **withdrawal** (↓); the chip's ring is the receiving kind's color. Hovering or focusing a chip says what moved; the readout above the chart lists every line's value at the hovered point, and that moment's Flow. | `charts a kind held earlier…`, `flow events` |
| W5 | **Daily change** is a bar per day in gain and loss colors, with the running total, from H6. **Days by kind** is the table behind it: each day split by kind. Days are UTC days (H6). | `charts a kind held earlier…` |
| W6 | On a wide screen (lg and up) the page fits one viewport and never scrolls: the total and Allocation, **Value** and **Daily change** stacked on the left, **Value** taking the spare height; the **Holdings** and **Days by kind** in a fixed column on the right, the table taking what the Holdings leave and scrolling inside itself under a pinned header. A narrow screen stacks them in reading order: total, Holdings, Value, Daily change, Days by kind. **Holdings** is one card per kind in the Allocation's order, headed by the kind's key, value, share of the total and change since the open: Perps (its USDC collateral and the open uPnL, N6, then the Portfolio margin as buying power, N10; trades are in the Journal), Spot rows (N6), LLP (shares, put in, value, APY), and Staking (LIT staked, LIT put in, value, APY) with pending unlocks. A kind not held says so. A mismatch (N5) is a warning above everything. | `lists what each Holding is made of`, `says so when value and PnL disagree` |
| W7 | **Days by kind** pages its days newest first, each page as many rows as fit the table's height (at least 5; 20 before it can measure), re-measured when the window resizes, keeping the newest day shown in view; with **Newer** and **Older**; a new range starts on the first page. **Export CSV** saves every day in the range, oldest first: `day_utc`, each kind, `total`, at the venue's full precision. | `pages the days, newest first, and exports them all as CSV` |
| W8 | **Calendar**, a button beside **PnL card**, opens a modal of one UTC month, always six weeks tall so paging never resizes it, Monday first, each day tinted in the gain or loss color by its change relative to the month's largest, with the week's total at the end of its row and the month's total beside its name. It reads every day (`range=all`, H6) each time it opens, whatever the range; months page from the first stored day to the current one. Hovering a day lists its kinds. | `opens the calendar in a modal…` |
| W9 | **PnL card** is a 1200×630 PNG to save or copy: the % and $ change, a running-PnL curve, the UTC dates and the range. The range is the page's span (`now`) or 7d, 30d, 90d, All; a range's change is the sum of its Day changes, and its % compounds each day's change over that day's opening value, so a deposit is not a gain. The curve is the total value's move less every Flow. **Show $** off leaves every dollar amount off the card. | `opens the PnL card…`, `portfolioShare` tests |

## Daily push

| | Rule | Pinned by |
|---|---|---|
| D1 | The daily Telegram push ([push-rules.md](push-rules.md), `push.daily_at`) leads with yesterday's Portfolio change: each kind's cumulative PnL at the end of that UTC day less at its start (V1, V4), from the stored `1d` buckets (H1), and the total. Only kinds that moved are named. It needs buckets stamped at **both** UTC midnights; with either missing it is left out rather than guessed, and the journal part goes out alone. The UTC day matches the journal part's day. | test_portfolio_day_totals_need_both_midnights, test_daily_text_leads_with_the_portfolio |
