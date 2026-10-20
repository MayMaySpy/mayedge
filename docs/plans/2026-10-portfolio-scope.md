# Portfolio — scope

Show everything the account owns, not just perps: spot holdings, LLP shares, staked LIT, pending unlocks and perp margin. Show what each is worth now, and how many dollars each made or lost **today** and over time, with deposits and withdrawals left out of the change.

Placement (decided): a `/portfolio` page, like `/journal`, plus a **Today** figure in the desk header next to MARGIN.

> **Step 0 is done** — see [docs/portfolio-rules.md](../portfolio-rules.md) "What the venue says". It changes the build:
> - The `pnl` endpoint answers **value** (with `ignore_transfers=true`), **cumulative PnL** and **cumulative Flows** for every Holding kind, by hour or day. Value, history and the Day change all come from it. Drop the `portfolio_samples` and `portfolio_hours` tables in §4. Store the venue's buckets (`portfolio_pnl`), one `1h` and one `1d` series in each of the two modes.
> - The mismatch check is rule V3: value less PnL against net Flows.
> - The account read is only for quantities, shares, APY and unlocks. LLP is pool `281474976710654`, LIT staking is `281474976624800` (rules P2, P3).
> - The account behind this scope holds Perps (USDC), Spot (ETH as collateral) and LIT staking. It has no LLP today; it left LLP on 2026-10-19.

Read [the October plan](2026-10-improvement-plan.md) §0 first. Its ground rules hold here: rules doc before code, commit to `main`, `make ci` green, and never place orders or move funds on the live desk. This feature only **reads**.

---

## 1. Words (add to CONTEXT.md)

- **Portfolio**: everything the account holds on Lighter, valued in USD. *Avoid: balance, equity, TAV (TAV is one part of it).*
- **Holding**: one line of the Portfolio. Its kind is one of:
  - **Perps**: collateral plus open uPnL.
  - **Spot**: a spot asset balance (LIT, ETH…), at its index price.
  - **LLP**: shares in the Lighter liquidity pool, at the pool's share price.
  - **Staking**: LIT in a staking pool, at the LIT price.
  - **Unlocking**: pending unlocks, at the asset price, with the date they free up.
- **Flow**: money moved into or out of a Holding — deposit, withdrawal, a transfer between perps and spot, joining or leaving LLP, staking or unstaking. A Flow is not a gain. *Avoid: transfer (that is one kind of Flow), PnL.*
- **Day change**: a Holding's value now, less its value at the day's open, less the net Flows into it since then. *Avoid: 24h change (that is the rolling one, below), return.*
- **Day open**: local midnight by default. A `portfolio.day_start` knob takes `local` or `utc`. A toggle on the page also shows a rolling 24h.

---

## 2. What the venue gives us (checked in the SDK, `lighter` package)

| Source | Fields | Use |
|---|---|---|
| `AccountApi.account(by="index", value=…)` → `DetailedAccount` | `assets[]` (symbol, asset_id, balance, locked_balance, margin_balance), `shares[]` (public_pool_index, shares_amount, entry_usdc, entry_timestamp, principal_amount), `pending_unlocks[]` (unlock_timestamp, asset_index, amount), `total_asset_value`, `cross_asset_value`, `collateral` | The Portfolio now |
| `AccountApi.public_pools_metadata(index, limit, filter=…)` → per pool `total_asset_value`, `total_shares`, `annual_percentage_yield`, `account_share`, `name` | **Share price = total_asset_value ÷ total_shares.** `filter="stake"` lists staking pools. | Valuing LLP and Staking |
| `AccountApi.pnl(by, value, resolution, start_timestamp, end_timestamp, count_back, ignore_transfers)` → `PnLEntry[]` | Per bucket: `trade_pnl`, `trade_spot_pnl`, `pool_pnl`, `staking_pnl`; `inflow`/`outflow`, `spot_inflow`/`spot_outflow`, `pool_inflow`/`pool_outflow`, `staking_inflow`/`staking_outflow`; `staked_lit`, `pool_total_shares`, `volume` | **The Day change and its history, already split by Holding kind and net of Flows.** This is the venue's own accounting; use it rather than re-deriving it. |
| Asset metadata (already used by the desk) | `index_price`, `price_decimals` | Spot prices, live |
| Account WS (already subscribed) | `account_all_assets`, `account_spot_avg_entry_prices` | Spot, live. The Assets tab already shows spot value and spot uPnL (`parse.public_assets`). |

Not used: `lit_lease` (that one signs a transaction; out of scope).

---

## 3. Step 0 — find out before building (one short commit, no UI)

Each of these is a guess until it's checked against the real account. Check them **through the desk**: add a temporary, read-only `GET /api/portfolio/raw` that returns the venue's raw `account`, `public_pools_metadata` (no filter, and `filter="stake"`) and one `pnl` call. Save one redacted response as `backend/tests/fixtures/portfolio_raw.json` for the tests, then remove the route.

1. **Timestamp units** for `shares[].entry_timestamp`, `pending_unlocks[].unlock_timestamp` and `PnLEntry.timestamp`. The journal shipped with fills in ms and funding in s, and every funding print was missed. Normalise everything to ms at the parse boundary, in one helper.
2. **`pnl` parameters**: valid `by` and `value` (probably `by="index"`, `value=<account_index>`), valid `resolution` strings (`1h`? `1d`?), and whether `count_back` or the start/end timestamps win. Check whether `ignore_transfers=true` changes the `*_pnl` fields or only the flows.
3. **Which pool is LLP**, and which pool(s) are staking: by `name` and `filter="stake"`. Do not hard-code an index without a comment saying where it came from.
4. **Double counting.** In a unified account, USDC collateral can also appear as a spot asset, and `total_asset_value` may already include spot. Work out exactly what `total_asset_value` and `cross_asset_value` include. Then define Perps and Spot so that **the sum of Holdings equals the venue's total** for the perps and spot part. Pool and staking value are extra unless the check shows otherwise. Write the identity into `docs/portfolio-rules.md`, and make it a test.
5. **Is staked LIT a pool share, an asset with a lock, or both?** `staked_lit` in the PnL entry and `pending_unlocks` suggest staking has its own path. Pick one place to value it, so it is counted once.
6. **Do `shares` and `pending_unlocks` arrive on the account WS, or only over REST?** That decides polling (below).

The answers go into `docs/portfolio-rules.md` as the first section, "What the venue says".

---

## 4. Backend

### Modules

- `backend/src/mayedge/portfolio.py`: pure functions, no I/O.
  - `holdings(account_raw, pools, asset_prices, positions) -> list[Holding]`. Each Holding has kind, symbol, qty, price, value_usd, plus the kind's extras: cost basis and uPnL for spot (from avg entry); entry_usdc, principal and share price for LLP; APY; unlock time for Unlocking.
  - `day_change(pnl_entries, since_ms) -> dict[kind, Decimal]`: sums `trade_pnl + (funding, if the venue folds it in — check in Step 0)` for Perps, `trade_spot_pnl` for Spot, `pool_pnl` for LLP and `staking_pnl` for Staking, over the buckets since the Day open. Also the Flows per kind.
  - `check(holdings_now, holdings_at_open, flows, change) -> mismatch`: value now − value at open − net Flows should equal the venue's PnL sum. Above $1 or 0.5%, show a flag on the page saying which kind disagrees. This is how a wrong field mapping gets caught in use.
- `backend/src/mayedge/portfolio_sync.py`: one loop, like `journal_sync`.
  - Account and pools every 60s. Skip the account call when the account WS already gives what's needed (Step 0, item 6).
  - The `pnl` endpoint every 5 minutes for today's hourly buckets. Backfill daily buckets once, as far as the venue goes, then extend daily.
  - Every call goes through the shared budget as `background` (`budget.take("background", wait=True)`), never ahead of orders. Read [docs/lighter-limits.md](../lighter-limits.md).
  - Off when `settings.trading_enabled` is False.
- `backend/src/mayedge/persist_portfolio.py` (bump `SCHEMA_VERSION`):
  ```sql
  CREATE TABLE IF NOT EXISTS portfolio_samples (   -- one row per kind per minute, 30 days
      ts INTEGER NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
      PRIMARY KEY (ts, kind)
  );
  CREATE TABLE IF NOT EXISTS portfolio_hours (     -- close per hour per kind, kept for good
      ts INTEGER NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
      PRIMARY KEY (ts, kind)
  );
  CREATE TABLE IF NOT EXISTS portfolio_pnl (       -- the venue's PnL buckets, kept for good
      ts INTEGER NOT NULL, resolution TEXT NOT NULL, raw TEXT NOT NULL,
      PRIMARY KEY (ts, resolution)
  );
  ```
  Follow `persist_oi.py`: minute samples kept 30 days, then rolled into hours. Store the `pnl` buckets raw, so a mapping fix needs no refetch.

### API (new router `api/routes/portfolio.py`)

- `GET /api/portfolio` → `{ts, total, day_change, day_change_pct, holdings: [...], by_kind: {kind: {value, day_change, flows}}, mismatch}`
- `GET /api/portfolio/history?range=1d|7d|30d|90d|all&resolution=` → value per kind over time (from samples), with Flows marked.
- `GET /api/portfolio/pnl?range=` → daily change per kind (from the venue buckets), for the bar chart.
- A WS message `{"type": "portfolio", total, day_change, by_kind}` once a minute, for the header. It is small, and the desk socket already exists.

---

## 5. Web

### Header strip
After MARGIN in `Header.tsx`: **Today +$123,40 (+1,2%)**, colored. Hovering shows the split: Perps, Spot, LLP, Staking. Clicking opens `/portfolio` in a new tab. It is hidden when trading is off.

### `/portfolio` page
Same shell as `JournalPage`: `isPortfolioPath` in `deskRoute.ts`, lazy-loaded in `App.tsx`, REST plus the one WS message.

1. **Top**: total value, Today $ and %, the rolling 24h toggle, and the mismatch flag when there is one.
2. **Allocation**: one horizontal bar split by kind, with $ and % of the total.
3. **Value over time**: a stacked area per kind (`lightweight-charts` area series, or the dataviz skill's guidance for a stacked chart). Ranges 1d / 7d / 30d / 90d / All. Flows show as markers, so a deposit is not read as a gain.
4. **Daily change**: bars per day, stacked by kind, from `/api/portfolio/pnl`. Same ranges.
5. **Holdings tables**, one section per kind:
   - Spot: asset, qty, price, value, avg entry, uPnL, today's $ change (qty × the price move since the Day open).
   - LLP: pool, shares, share price, value, entry USDC, PnL since entry, APY.
   - Staking: staked LIT, value, staking PnL, APY.
   - Unlocking: amount, value, unlocks on (date and time left).
   - Perps: collateral, uPnL, margin used — with a link to the Journal for trades.
6. Links: Desk, Journal.

Reuse `journalFormat.ts` for money, percent and price formatting. Its `price()` handles small coins.

---

## 6. Telegram (small, after the page)

Add today's Portfolio change to the daily push (`push.daily_at`): `Yesterday: Portfolio +$412 (Perps +$380, Spot +$40, LLP +$6, Staking −$14) · Net trading +$380 over 9 Round trips`.

---

## 7. Out of scope

- Moving money: depositing to or leaving LLP, staking, unstaking, transfers, `lit_lease`. The desk only reads here.
- Sub-accounts and more than one account.
- Tax lots or realized-gain reports.
- Valuing anything outside Lighter.

---

## 8. Tests

- `test_portfolio.py` (pure, on the Step 0 fixture):
  - the sum identity from Step 0, item 4;
  - LLP value = shares × total_asset_value ÷ total_shares;
  - staking counted once;
  - unlocks dated in ms;
  - day change per kind from fixed buckets, including a deposit that must not count;
  - the mismatch flag fires when value and PnL disagree.
- `test_portfolio_sync.py`: budget taken per call; off without trading; backfill is idempotent; an interrupted backfill is finished later (the journal bug, again).
- API: shapes, and a Flow never shows as change.
- Web: header strip renders and colors; the page renders each section from fixtures; the 24h toggle switches the source.

## 9. Order

| Step | What | Size |
|---|---|---|
| 0 | Discovery, fixture, `docs/portfolio-rules.md` "What the venue says" | S |
| 1 | `portfolio.py` + `GET /api/portfolio` (now only) | M |
| 2 | Sync, samples, PnL buckets, history and PnL endpoints | M |
| 3 | Header strip + WS message | S |
| 4 | `/portfolio` page | M–L |
| 5 | Daily push line | S |

Steps 3 and 4 can run side by side once step 2 is in. Every step ends with `make ci` green and the rules doc updated in the same commit.

## 10. Risks

- **Double counting** USDC or staked LIT between Perps, Spot and Staking. Step 0, items 4 and 5, plus the sum test.
- **ms vs s** timestamps. Step 0, item 1.
- **Share price lag**: the pool's `total_asset_value` may update less often than prices. Show the share price's age on the page.
- **Rate budget**: the account plus pools every 60s is two calls a minute in the background lane. Drop the account call if the WS covers it.
- **The venue's PnL fields may not mean what their names say.** The mismatch check exists to catch that early. Do not hide it.
