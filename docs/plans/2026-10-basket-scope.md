# Baskets — weighted sets of coins and the Rebalancer, scope

Hold a set of coins at weights the operator chooses: some long, some short, some spot. Keep the set at those weights with a Rebalance on a calendar, on drift, or only when the operator changes it. Run it on paper first, test it against the desk's own history, and then trade it from the browser.

This is the hosted desk's first product. It is built on the TypeScript desk from [the hosted desk migration plan](2026-10-hosted-desk-migration.md), not on the Python desk. It fits that plan's deal on purpose: a Rebalance happens once a day, a week or a month, so it never needs a tab open in between. The server watches and says when a Rebalance is due. The operator opens the tab, reads the orders, and signs them in one approval.

Placement: a **Baskets** list on the Ideas page, next to the Ideas list, and a Basket's own page at `/baskets/{id}`.

Read the migration plan's Ground rules first. They hold here: rules doc before code ([ADR 0011](../adr/0011-alert-rules-are-written-down-before-they-are-coded.md)), commit straight to `main`, `make ci` green before every commit, and testnet only for every signed transaction until that plan's checkpoint 2.

---

## 0. The name (decide before step 1)

The operator asked for a "portfolio". [CONTEXT.md](../../CONTEXT.md) already uses **Portfolio** for everything the account holds on Lighter (Perps, Spot, LLP, Staking), and the header's **Today** is built from it. Two meanings would make every rule ambiguous.

> Decided unless the operator says otherwise: the set is a **Basket**, its coins are **Parts**, and the algo is the **Rebalancer**. "Port manager" is not used. If the operator wants a different word, pick it now and use it everywhere.

A Basket is not an Idea. An Idea is one Market and one side, and an Idea never sends an order ([idea-rules.md](../idea-rules.md) I1, [ADR 0020](../adr/0020-an-idea-is-a-note-not-an-order.md)). Both stay true. A Basket sits beside Ideas, can be started from Ideas, and is traded only by the Rebalancer, only after the operator approves.

---

## 1. Words (add to CONTEXT.md, section "Baskets", after "Ideas")

**Basket**:
A set of Parts held at Target weights, in one sub-account of its own. It is traded only by the Rebalancer, and only after the operator approves a Rebalance plan. The rules are in [docs/basket-rules.md](docs/basket-rules.md).
_Avoid_: portfolio (that is everything the account holds), index, fund, strategy, book

**Part**:
One Market in a Basket, with a kind (long, short or spot) and a Target weight.
_Avoid_: leg (that is a Planner's or an OCO's), position (that is the venue's), holding (that is the Portfolio's), constituent

**Target weight**:
A Part's share of the Basket's gross exposure, in percent. A Basket's Target weights add up to 100.
_Avoid_: allocation (the Portfolio page uses it), weight (unqualified, when Current weight is near), size

**Current weight**:
A Part's notional now, as a share of the Basket's gross exposure at target.
_Avoid_: actual, live weight

**Basket value**:
The sub-account's collateral plus its uPnL plus the value of its spot assets, in USD.
_Avoid_: equity, NAV, balance, TAV

**Gross leverage**:
The Basket's gross exposure over its Basket value. Set per Basket; 1× by default.
_Avoid_: leverage (unqualified: that is a Market's margin setting)

**Drift**:
Current weight minus Target weight, in percentage points.
_Avoid_: deviation, tracking error (that is a statistic over time), imbalance

**Drift band**:
How far a Part may Drift before a Rebalance trades it back, in percentage points.
_Avoid_: threshold (unqualified), tolerance

**Rebalance mode**:
When a Basket Rebalances: Hold, Calendar, Band, or Calendar and band.
_Avoid_: schedule (that is Calendar only), frequency

**Rebalance**:
One pass that brings Parts back to their Target weights. It starts as a Rebalance plan and ends Done, Partial, Failed, Missed or Skipped.
_Avoid_: rebalancing (as a noun), reset, sync

**Rebalance plan**:
The orders a Rebalance would send, with their sizes, prices, kinds and estimated cost. Nothing is sent until the operator approves it.
_Avoid_: Plan (that is an Idea's), order list, preview, Draft (that is the chart's)

**Rebalancer**:
The algo that turns an approved Rebalance plan into orders, in the tab that approved it.
_Avoid_: port manager, portfolio manager, bot

**Paper Basket**:
A Basket with no sub-account and no orders. The server fills its Rebalances at Last on its own, so it runs with no tab open.
_Avoid_: demo, simulation, dry run

**Backtest**:
A Basket replayed over a past window from the desk's own history: price hours and Funding prints.
_Avoid_: simulation, what-if (that is the Alerts panel's), Paper Basket (that runs forward)

**Basket return**:
The Basket's time-weighted return: transfers in and out do not count as gains or losses.
_Avoid_: PnL (unqualified), performance, ROI

---

## 2. What already exists and gets reused

| Need | Already there (TypeScript desk) | Note |
|---|---|---|
| Prices of every Part | market feed, `market_stats/all` | Last per Market, same as Ideas |
| Funding of every perp Part | Funding prints, Funding average | The cost of holding a Part, before and after |
| Market metadata | `orderBookDetails` | maker minimums, size and price decimals |
| Signing, nonces, budget | `web/src/venue/` | migration plan section 4 |
| Order building and checks | `core/venue/orderBuild.ts` | maker minimum at the order's own price, notional cap |
| Venue TWAP | order type 6 | runs on Lighter after the tab closes |
| Read-only token, per-user jobs | migration plan sections 3.6 and 3.7 | the server watches Drift with it |
| Pushes | migration plan section 3.9 | new events in section 12 |
| Journal | per user | gains an account index (section 11) |
| History for Backtests | migration plan section 2.10 | gains price hours (section 10) |

New: sub-accounts, spot orders, the Basket client_order_index band, the Rebalancer, Paper Baskets and Backtests.

---

## 3. Rules (write `docs/basket-rules.md` first, in the step-1 commit)

### A worked Basket

A Basket of $10,000 at 1× Gross leverage, Band mode, Drift band 2 points:

| Part | Kind | Target weight | Target notional |
|---|---|---|---|
| BTC | long | 50 | +$5,000 |
| ETH | long | 30 | +$3,000 |
| SOL | short | 20 | −$2,000 |

Gross $10,000, net $6,000 long.

BTC rises 10% and nothing else moves. BTC is now $5,500 and the Basket value is $10,500. Targets at 1× are BTC $5,250, ETH $3,150, SOL −$2,100.

- BTC Drift = (5,500 − 5,250) / 10,500 = **+2.38** points. Past the band.
- ETH Drift = (3,000 − 3,150) / 10,500 = **−1.43** points. Inside.
- SOL Drift = (2,000 − 2,100) / 10,500 = **−0.95** points. Inside.

The Rebalance plan sells $250 of BTC. ETH and SOL stay as they are.

### Shape

| | Rule | Knob |
|---|---|---|
| B1 | A Basket has a name (1–40 characters), 1–20 Parts, a Rebalance mode, an execution kind and a Gross leverage. A Thesis is optional, with the same rules as an Idea's. | code |
| B2 | A Part is a Market by symbol, a kind (`long`, `short`, `spot`) and a Target weight. A Market appears in a Basket at most once. | code |
| B3 | Target weights are decimal strings with at most 2 decimals, each > 0, and add up to exactly 100. The page offers "Equal weight", which splits 100 and gives the rounding remainder to the first Part. | code |
| B4 | A `spot` Part needs a spot Market for that coin. It can only be long and is never levered. | code |
| B5 | A long or short Part needs a perp. Binary options and unknown market types are refused, the same as the rest of the desk. | code |
| B6 | Gross leverage is 1× to 5×, in steps of 0.5. Perp Parts carry it; spot Parts are always 1× and are paid for in full. | `max_gross_leverage: 5` |
| B7 | A Basket can be made from Ideas: each chosen open Idea becomes a Part with its Market and side, and keeps a link back to the Idea. Changing the Idea later does not change the Part. | |
| B8 | A Basket's Parts and weights can change at any time. A change makes a Rebalance due at once, in every mode, Hold included. | |

### Sizing

| | Rule | Knob |
|---|---|---|
| Z1 | Target notional of a Part = Basket value × Gross leverage × Target weight / 100, signed by kind (short is negative). | code |
| Z2 | Cash needed = the sum of spot Parts' notional + the sum of perp Parts' notional / that Market's leverage. It must stay at or below Basket value × (1 − cash buffer). A Basket that breaks this is refused when saved and before every Rebalance plan. | `cash_buffer: 10%` |
| Z3 | **Minimum Basket value**: the smallest Basket value at which every Part's Target notional is at least 2× that Market's maker minimum (the stricter of `min_base_amount` × Last and `min_quote_amount`). The page shows it while the Basket is being built and refuses a Basket below it. | `min_part_multiple: 2` |
| Z4 | A Rebalance order below the Market's minimum is left out of the plan and listed as "under the venue minimum". Its Drift stays. | |
| Z5 | Sizes round down to the Market's size decimals. Prices round toward the touch to its price decimals. | code |

### Rebalance mode

| | Rule | Knob |
|---|---|---|
| R1 | **Hold**: a Rebalance is due only on a change (B8) or a transfer in or out. | |
| R2 | **Calendar**: a Rebalance is due daily, weekly (on a chosen weekday) or monthly (on a chosen day 1–28), at a chosen UTC time. Every Part trades back to target. | `calendar_at: "00:05"` |
| R3 | **Band**: the server checks Drift every 5 minutes. A Rebalance is due when any Part passes the Drift band; only the Parts past the band trade. | `band_check_s: 300`, `drift_band: 2` |
| R4 | **Calendar and band**: on the calendar time, only the Parts past the band trade. Nothing is due between calendar times. | |
| R5 | A due Rebalance makes a Rebalance plan and a Push (section 12). The plan is good for its approve window. After that it is **Missed**. | `approve_window_h: 24` |
| R6 | Missed policy, per Basket: **On next open** makes a fresh plan when the operator next opens the Basket; **Skip** waits for the next due time. | default On next open |
| R7 | Drift is read from the sub-account's positions and spot assets (read-only token) and Last. The server never uses a price older than 60 s for a plan; with none, the plan waits and says why. | |

### Execution

| | Rule | Knob |
|---|---|---|
| E1 | Execution kinds: **Market** (IOC limit at the worst price allowed by the slippage cap), **Limit** (post-only at the touch; after the wait, the rest goes as Market or is left, per Basket), **TWAP** (venue TWAP over a duration). | `slippage_cap: 0.5%`, `limit_wait_m: 10`, `twap_m: 60` |
| E2 | The first build of a Basket may give each Part its own entry: Market, TWAP, or a Limit at a price the operator types (GTT, resting on the venue). Later Rebalances use the Basket's execution kind. | |
| E3 | Order of a Rebalance: (1) cancel the Basket's own resting orders, found by its client_order_index band; (2) send every reduction and every sell, reduce-only; (3) when (2) is done, send every increase. A Part that flips from long to short closes first in (2) and opens in (3). | code |
| E4 | With Market, (3) starts after (2)'s fills arrive on the account feed. With Limit and TWAP, (3) starts when (2) is sent, and Z2 is checked against the worst case of (2) not filling. | code |
| E5 | Before (3), the Rebalancer checks the sub-account's available margin. If it is short, every increase is scaled down by the same factor, and the plan says so before approval. | |
| E6 | Basket orders use the Basket band `[13e9, 14e9)` of client_order_index, added to [lighter-limits.md](../lighter-limits.md). | code |
| E7 | A Rebalance sends at most 30 transactions a minute: the algo ceiling of the Send budget. Twenty Parts plus their cancels fit in one minute; more waits for the next. | |
| E8 | A Rebalance ends **Done** when every order filled or was finished by the venue, **Partial** when some Part is left (each one listed with its reason), **Failed** when nothing was sent. A Partial Rebalance offers "Retry the rest", which makes a new plan for the Parts still past target. | |
| E9 | Market and Limit need the tab open until the Rebalance ends. TWAP and resting Limits keep working on the venue after it closes. The Rebalance review says which is which, in one sentence. | |

### Approval

| | Rule | Knob |
|---|---|---|
| A1 | Nothing reaches the venue until the operator approves a Rebalance plan in the tab that holds the signer. One approval signs every order in the plan. | |
| A2 | The review shows each order (Market, side, size, notional, kind, price or cap), the Drift before and after, the parts left out and why, the estimated cost (slippage at the cap, fees), and the funding the Basket would pay or receive a day after it. | |
| A3 | A plan older than 60 s is rebuilt before it is signed. The operator sees the new numbers before the signature. | code |
| A4 | Approving a plan never approves the next one. There is no "always approve" in v1. | |

### Sub-account

| | Rule | Knob |
|---|---|---|
| U1 | Each live Basket has its own Lighter sub-account. A sub-account holds at most one Basket. A Basket never trades the main account. | |
| U2 | Creating a live Basket creates its sub-account, registers an API key on it in the same browser, and moves the chosen amount into it. The steps are in section 8. | |
| U3 | While a sub-account holds a Basket, the desk's Order panel on that account offers only Kill. Kill cancels the Basket's orders, flattens when asked, and **pauses** the Basket. | |
| U4 | Moving money in or out is a **Basket transfer**. It is never counted in the Basket return. It makes a Rebalance due (R1). | |
| U5 | Closing a Basket offers: flatten everything and move the money back, or leave the positions in the sub-account and stop managing them. | |

### Paper Basket

| | Rule | Knob |
|---|---|---|
| Q1 | A Paper Basket starts at a chosen Basket value and holds no sub-account and no key. | |
| Q2 | The server runs its Rebalances on its own, with no approval: nothing reaches the venue. | |
| Q3 | Fills are at Last plus the paper slippage, against the side traded. | `paper_slippage: 0.10%` |
| Q4 | Perp Parts pay or receive each hour's Funding print on their notional. Fees use the paper fee. | `paper_fee: 0` |
| Q5 | A Paper Basket can become live: the live Basket starts from the same Parts and weights, not from the paper positions. | |

### Backtest

| | Rule | Knob |
|---|---|---|
| T1 | A Backtest replays a Basket's Parts, weights, mode and Gross leverage over 30, 90 or 365 days, or a UTC span, in hourly steps. | |
| T2 | Prices are price hours (section 10). Funding is Funding prints, then Funding days. A Part with no history at the window's start refuses the Backtest and names the first day it has. | |
| T3 | Calendar Rebalances happen at their hour. Band is checked every hour. Fills are at the hour's close plus the paper slippage. | |
| T4 | A Backtest returns: the value series, the Basket return, annualised volatility, the largest drawdown, turnover, funding paid and received, the number of Rebalances, and the same Basket in Hold and BTC long as references. | |
| T5 | A Backtest is a fact about the past; the page says so under every result. | |

### Basket return and value

| | Rule | Knob |
|---|---|---|
| V1 | The server records each live Basket's Basket value every hour from its sub-account (read-only token). | |
| V2 | Basket return is time-weighted: each Basket transfer starts a new sub-period, and the sub-period returns chain. | code |
| V3 | Each Part's share of the return is its realised and unrealised PnL plus its funding, from the Journal on that sub-account. | |
| V4 | The Basket page shows the Basket return against Hold of the same Basket and BTC long, from the Basket's first day. | |

---

## 4. ADRs (next free numbers after the migration plan's)

- **A Basket trades only after its owner approves a Rebalance plan.** The server proposes and the browser signs. It is the same line as ADR 0020 and the migration plan's D1, carried to an algo.
- **One Basket, one sub-account.** Lighter keeps one position per Market per account. A Basket that shared an account with manual Tickets could not tell its ETH from the operator's, and a Rebalance would trade against a manual position.

---

## 5. Server

### Migration

| Table | Columns |
|---|---|
| `baskets` | `id`, `user_id`, `name`, `thesis`, `status` (`paper`, `live`, `paused`, `closed`), `mode`, `calendar` (JSON: period, weekday or day, `HH:MM`), `drift_band`, `exec_kind`, `exec_knobs` (JSON), `gross_leverage`, `missed_policy`, `account_index` (null on paper), `created_at`, `closed_at` |
| `basket_parts` | `basket_id`, `market_symbol`, `kind`, `target_weight` (decimal string), `idea_id` (nullable), `position` |
| `basket_changes` | `basket_id`, `at`, `before` (JSON), `after` (JSON): every change of Parts, weights or knobs |
| `basket_rebalances` | `id`, `basket_id`, `due_at`, `reason` (`calendar`, `band`, `change`, `transfer`, `retry`), `plan` (JSON), `status`, `approved_at`, `ended_at`, `summary` (JSON) |
| `basket_orders` | `rebalance_id`, `market_index`, `client_order_index`, `side`, `size`, `kind`, `state`, `filled_size`, `avg_price`, `reason` |
| `basket_values` | `basket_id`, `hour_ms`, `value`, `transfer_in`, `transfer_out` |
| `basket_paper` | `basket_id`, `market_symbol`, `size`, `avg_price`, `funding_paid` |
| `price_hours` | `market_index`, `hour_ms`, `open`, `high`, `low`, `close`, `volume` (market history; section 10) |

Every Basket table has `user_id` through `baskets` and is covered by the migration plan's isolation test (3.2).

### Modules

| Module | Job |
|---|---|
| `core/basket/rules.ts` | B, Z, R, E3–E5, Q, T and V rules as pure functions: Drift, Target notional, cash needed, Minimum Basket value, plan building, order of operations, time-weighted return |
| `core/basket/plan.ts` | Build a Rebalance plan from Parts, positions, Last and market metadata |
| `core/basket/backtest.ts` | The replay (T1–T4), pure, fed rows |
| `server/src/user/basketWatch.ts` | Due times, Drift checks (R2–R4), plans, Missed, Pushes |
| `server/src/user/basketPaper.ts` | Paper Rebalances and hourly funding (Q2–Q4) |
| `server/src/user/basketValues.ts` | Hourly Basket value (V1) |
| `server/src/market/priceHours.ts` | Record and backfill price hours |
| `server/src/workers/backtest.ts` | Runs `core/basket/backtest.ts` in a worker thread |
| `web/src/venue/rebalancer.ts` | Runs an approved plan (E1–E9) |

### API

| Route | Does |
|---|---|
| `GET /api/baskets` | The user's Baskets with Basket value, Basket return, largest Drift and next due |
| `POST /api/baskets` | Create (paper by default) |
| `GET /api/baskets/{id}` | Parts with Target and Current weight and Drift, rebalances, value series |
| `PATCH /api/baskets/{id}` | Change Parts, weights or knobs (B8) |
| `POST /api/baskets/{id}/status` | Pause, resume, close |
| `GET /api/baskets/{id}/plan` | The current Rebalance plan, built fresh (A3) |
| `POST /api/baskets/{id}/rebalances/{rid}/approved` | The tab reports it approved a plan and is sending |
| `POST /api/baskets/{id}/rebalances/{rid}/orders` | The tab reports each order's state as the account feed shows it |
| `POST /api/baskets/{id}/rebalances/{rid}/ended` | The tab reports the end status (E8) |
| `POST /api/baskets/{id}/live` | Ties a Paper Basket to its new sub-account (Q5, U2) |
| `POST /api/backtests` | Runs a Backtest; at most 10 an hour per user |
| `GET /api/baskets/minimum` | Minimum Basket value for a set of Parts (Z3), for the dialog |

The server never receives a key or a signature for a Basket. The tab tells it what it sent, and the server checks the tab's report against the sub-account (read-only token) on its next pass.

### Budget

Per live Basket, on the user's own wallet: Drift checks in Band mode, 1 request every 5 minutes (0.2 a minute); Basket value, 1 an hour; Calendar mode, 1 at each due time. Ten Band Baskets stay at 2 a minute, inside the migration plan's 6 a minute per user.

---

## 6. Web

### Files

```
web/src/components/baskets/
  BasketList.tsx          the Ideas page's Baskets list
  BasketPage.tsx          /baskets/{id}
  BasketDialog.tsx        new and edit
  PartsTable.tsx          Target, Current, Drift, notional, funding
  RebalanceReview.tsx     the approval (A2)
  RebalanceRun.tsx        progress while the Rebalancer sends
  BacktestPanel.tsx
  BasketValueChart.tsx    Basket return against Hold and BTC
  GoLiveDialog.tsx        sub-account, key, transfer (section 8)
web/src/hooks/useBasket.ts, useBacktest.ts
web/src/lib/basketFormat.ts
```

### Ideas page

- The left column gets two tabs: **Ideas** and **Baskets**.
- The Ideas list gains a checkbox column while "Make a Basket" is on; the chosen Ideas open the Basket dialog with their Markets and sides (B7).

### Basket dialog

- Name, optional Thesis.
- Parts: a Market picker (perps, and spot where the coin has a spot Market), kind, Target weight. "Equal weight". The total shows and turns red until it is 100.
- Mode and its knobs. Execution kind and its knobs. Gross leverage.
- Live under the table: Minimum Basket value (Z3), cash needed (Z2), net and gross exposure, and the funding the Basket would pay or receive a day at today's Funding average.
- Create as Paper (default). "Go live" is on the Basket page, not here.

### Basket page

- Header: name, status, Basket value, Basket return, next due, largest Drift.
- Parts table: Market, kind, Target weight, Current weight, Drift (red past the band), notional, uPnL, funding a day.
- Value chart: Basket return against Hold and BTC (V4).
- Rebalances list with status, reason and summary; each opens its orders.
- Backtest panel: window, mode override, Run. The result draws over the value chart's axes.
- Actions: Rebalance now (makes a plan in every mode), Pause, Go live (paper only), Transfer in, Transfer out, Close.

### Rebalance review and run

- The review is a dialog (A2). The primary button is "Sign and send N orders". With E9's sentence above it.
- The run view lists each order with its state from the account feed, and ends with the E8 status. Closing the tab during Market or Limit leaves a Partial; the server marks it so on its next pass.

### Type and color

Follow `.cursor/rules/typography.mdc`. Long is green and short is red, as in the New idea dialog; spot is the neutral foreground.

---

## 7. Spot

The desk does not trade spot today. A Basket needs it for spot Parts.

- `orderBookDetails` lists spot Markets separately. The desk already reads both lists and skips spot for Scan and alerts; the Basket dialog lists them.
- Spot orders are signed like perp orders with the spot Market's index (migration plan spike S12 confirms).
- Spot assets come from `account_all_assets` on the account feed, which the desk already reads for Assets.
- A spot Part's notional is its asset balance × Last. Its fills land in the Journal like any other.
- Whether spot assets count as perp collateral changes Z2. Spike S13 answers it; until then Z2 treats spot as fully paid and not collateral.

---

## 8. Going live (sub-account, key, transfer)

Each step is tried on testnet in the migration plan's spikes S11–S14 before it is built.

1. The operator chooses Go live and an amount.
2. The tab creates a sub-account under the main account (signed with the main account's API key, or the L1 wallet if the venue asks for it).
3. The tab generates a key for the sub-account in the signer worker and registers it (ChangePubKey on the sub-account's index). The vault keeps one record per (account, API key index).
4. The tab moves the amount from the main account into the sub-account.
5. The server's read-only token must see the sub-account: if the token is `all`-scoped and covers sub-accounts, nothing more; otherwise the tab makes a token for the sub-account (another 10,000 request weight) and hands it over.
6. `POST /api/baskets/{id}/live` ties the Basket to the sub-account.
7. The first Rebalance plan is the build, with E2's per-Part entries. The operator approves it.

The desk's account picker lists Basket sub-accounts with their Basket's name. The Web Lock (migration plan D4) is per (account, key), so the Rebalancer for a Basket and manual trading on the main account can run in one tab.

---

## 9. Paper Baskets

- Run on the server every minute against Last; no tab, no key, no sub-account.
- Paper Rebalances follow the same mode rules and write the same `basket_rebalances` rows with `status = done` and paper fills in `summary`.
- Paper Baskets need nothing from section 4 of the migration plan, so they ship after its section 3 (step order, section 15).

---

## 10. Price hours (market history)

Backtests must not read the venue per request: that would make the server's public budget grow with users (migration plan D11). So the server keeps its own hourly bars.

- `price_hours`: one row per perp and spot Market per UTC hour: open, high, low, close, volume.
- Recorded live from the market feed's 1m candles, folded at each hour's close.
- Backfilled once per Market from the venue's 1h `candles`, up to 365 days, on the `background` lane. About 18 requests per Market at most; 100 Markets is about 1,800 requests, a little over an hour at the background ceiling.
- Kept for good. Added to the migration plan's market history table (2.10), its Backup and its gaps: a Backtest across a recorded gap uses the bars on each side and lists the gap in its result.

---

## 11. Journal and Portfolio

- Journal tables gain `account_index` with the migration's `user_id`, so a Basket's Round trips stay in its sub-account and the main account's Journal is unchanged.
- The Journal page gets an account filter: All, Main, each Basket.
- The Portfolio already reads the account; with sub-accounts it shows Main and each Basket as Holdings of the total. Write this into [portfolio-rules.md](../portfolio-rules.md) first.

---

## 12. Pushes

New events, added to [push-rules.md](../push-rules.md) before the code:

| Event | Text, roughly | When |
|---|---|---|
| Rebalance due | "Basket Majors: rebalance due. BTC +2.4 pts. Open to review." | R5 |
| Missed | "Basket Majors: rebalance missed (24h). Next: on open." | R5 |
| Rebalance ended | "Basket Majors: rebalance Partial. 7 of 8 Parts; SOL under the venue minimum." | E8 |
| Part not listed | "Basket Majors: XYZ is no longer listed. The Basket is paused." | a Part's Market leaves the venue list |
| Near liquidation | the existing event, now for Basket sub-accounts | the migration plan's Positions poll covers each sub-account |

Paper Baskets push only "Rebalance ended" and only when the operator turns it on.

---

## 13. Out of scope (v1)

- Approving without the operator (auto-approve while a tab is open, or at all).
- Chase as an execution kind. It arrives with the rest of the algos.
- Weighting by inverse volatility, risk parity or market cap. Fixed and equal weight only. Inverse volatility from price hours is the first one after v1.
- A Basket-level stop or drawdown limit. It would be its own rule, separate from Auto kill, which stays uPnL-only.
- Sharing or copying a Basket between users.
- CSV export.
- More than 20 Parts.

---

## 14. Tests

- Every rule ID in `basket-rules.md` names its test, as `idea-rules.md` does.
- `core/basket/rules.ts`: the worked Basket above, as a test; Drift with shorts and spot; Z2 refused and accepted; Z3 at the edge; Z4 left out; E3 ordering including a flip; E5 scaling; V2 with two transfers.
- `core/basket/backtest.ts`: a fixed 30-day fixture of price hours and Funding prints; Hold, Calendar weekly and Band give known results; a missing Part refuses (T2).
- Rebalancer against the ported fake venue: Market with all filled; Limit with the wait running out; TWAP; a Partial; a closed tab during Market.
- Server: due times across month ends and weekdays in UTC; Missed and both policies; a stale price refuses a plan (R7); isolation between two users.
- Testnet: one live Basket of 3 perps and 1 spot built, Rebalanced in Band mode, and closed (U5), before checkpoint 2.

---

## 15. Order

1. Words, `basket-rules.md`, ADRs. No code.
2. `core/basket/rules.ts` and `plan.ts`, with their tests.
3. Price hours: recording and backfill (section 10).
4. Paper Baskets: tables, routes, `basketPaper.ts`, Basket dialog, Basket page, Baskets list. **Ships after migration plan section 3.**
5. Backtests: `backtest.ts`, the worker, `BacktestPanel`.
6. Spot orders (section 7), after spikes S12–S13.
7. Sub-accounts and Go live (section 8), after spikes S11 and S14.
8. The Rebalancer, the review and the run (E, A). **After migration plan section 4.**
9. Basket value, Basket return, Journal and Portfolio by account (V, section 11).
10. Pushes (section 12).
11. Testnet live Basket (section 14, last line).

---

## 16. Risks

| Risk | What it costs | What this scope does |
|---|---|---|
| Lighter cannot create a sub-account, register a key on it, or transfer into it from a browser | No live Baskets as designed | Spikes S11–S14 first. Fallback: one live Basket per user on the main account, and the desk refuses manual Tickets on its Markets |
| A Rebalance half-runs when the tab closes | A Basket left between old and new weights | E3 sends reductions first; E8 marks Partial; the server sees it on its next pass and offers Retry |
| Small Baskets hit venue minimums | Parts that never trade back | Z3 refuses them at creation; Z4 says which order was left out |
| A Backtest looks like a promise | Users trust a past number | T5 under every result; slippage and fee knobs shown with it |
| Funding eats a long-short Basket | Slow losses nobody sees | The dialog and the Parts table show funding a day; Basket return includes it |
| Shorts or leverage near liquidation in a sub-account | A liquidated Part | Near liquidation Pushes for each sub-account; Gross leverage capped at 5× |

---

## 17. Open questions for the owner

1. "Basket" and "Rebalancer", or other words?
2. Default execution kind: Market, Limit or TWAP?
3. Should a Paper Basket be public (a link anyone can view) from the start? It holds no account data.
4. The 20-Part cap: enough?
5. Is the first weighting after fixed and equal: inverse volatility?
