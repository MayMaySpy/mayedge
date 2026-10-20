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
| A1 | `total_asset_value` equals `collateral`, which is USDC's `margin_balance`. That is the Perps value (V2 agrees). USDC's spot `balance` was 0. **USDC is never counted as Spot.** |
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
- A **Day open** at local midnight uses `1h` buckets; at UTC midnight, `1d` works as well.
- The mismatch check in the scope becomes V3: if value less PnL drifts from net Flows by more than a dollar, a field changed meaning.
