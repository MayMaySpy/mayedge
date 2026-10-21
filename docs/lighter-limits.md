# Lighter venue limits (reference)

Cross-check against official docs before changing algo behavior:

- [Rate limits](https://apidocs.lighter.xyz/docs/rate-limits)
- [Trading / signing](https://apidocs.lighter.xyz/docs/trading)
- [Data structures & errors](https://apidocs.lighter.xyz/docs/data-structures-constants-and-errors)

Last reviewed: 2026-10-21.

Mayedge stays on **Standard** (0 fees). The send budget in `lighter/budget.py` is built for that tier. Nothing in the desk assumes Premium.

The header's feed status shows that budget for the last 60 seconds: sends against 38, requests against 54. The line turns amber when sends reach the algo cap of 30, so a manual order still fits. It turns red while Lighter's cooldown is running, and names the UTC time the cooldown ends.

## Active orders (on book)

Limit orders resting in the book count as **active**.

| Account type | Per account | Per market |
|--------------|-------------|------------|
| Standard     | 250         | **30**     |
| Plus         | 750         | 250        |
| Premium      | 1500        | 1000       |

Relevant errors: `AppErrMaxOrdersPerAccount` (21717), `AppErrMaxOrdersPerAccountPerMarket` (21718).

**Mayedge policy:** treat **20 live algo children per market** as the practical cap (leave headroom for chase, manuals, and venue limit 30 on Standard).

## Pending orders

TP/SL/TWAP **parent** orders (not yet on book). TWAP sub-orders skip pending limits.

| Account type | Per account | Per market |
|--------------|-------------|------------|
| Standard     | 50          | 10         |
| Plus         | 500         | 100        |
| Premium      | 1000        | 100        |

Desk algos (chase, ladder, advanced TWAP) place **active** post-only limits — not pending parents.

## Maker minimums

Per market from `orderBooks` / `orderBookDetails`:

- `min_base_amount`, `min_quote_amount` — **the stricter applies** to maker (post-only / GTT) orders.
- Price and size use market `price_decimals` / `size_decimals`.

Error: `AppErrInvalidOrderBaseOrQuoteAmount` (21706).

## Order types we use

| Type | ID | Notes |
|------|-----|--------|
| Limit | 0 | Desk algo children |
| Market | 1 | Kill flatten, ticket market |
| Stop Loss | 2 | Position-row protect; market parent |
| Stop Loss Limit | 3 | Position-row protect |
| Take Profit | 4 | Position-row protect; market parent |
| Take Profit Limit | 5 | Position-row protect |
| TWAP | 6 | Venue-native TWAP (ticket, not desk book) |

## Time in force

| TIF | ID | Desk usage |
|-----|-----|------------|
| IOC | 0 | Ticket market-style limits |
| GTT | 1 | Manual limits |
| Post-only | 2 | **All desk algo children** |

Post-only rejects would-cross (`2170*` family) instead of taking.

## Order expiry

GTT limits: expiry between **5 minutes and 30 days** (ms timestamp). We use SDK default 28-day expiry for limits.

## Transaction / API rate limits

Reviewed against the venue's rate-limits and trading pages on 2026-10-21. Standard requests are unweighted, 60 per rolling minute. When `24000 / weight` is below 60, that lower number is the cap (`changeAccountTier`, weight 3000, is 8 per minute). The desk does not call `changeAccountTier`, `recentTrades` (weight 600, which would be 40 per minute), or `transferFeeInfo`.

Endpoints the desk calls, and the Standard cap that follows:

| Endpoint | Weight | Standard cap |
|----------|--------|----------------|
| `sendTx`, `sendTxBatch`, `nextNonce` | 6 | 60 |
| `accountActiveOrders` | 100 | 60 |
| `trades` | 200 | 60 |
| `orderBookDetails`, `candles`, `fundings`, `account`, `accountLimits`, `assetDetails`, `pnl`, `positionFunding` | 300 | 60 |

`24000 / weight` is above 60 for every one of those, so each stays at 60. `sendTx` and `sendTxBatch` also sit in the 60 for a Standard account. Premium's separate send bucket does not apply.

Transaction type limits apply on top of the 60. The default type, including order create and cancel, is 40 per minute. `L2UpdateLeverage` is also 40 per minute. The desk's own ceilings are 38 transactions and 54 requests, with algos held to 30 transactions so a manual order still fits.

A grouped Stop plus Take Profit counts as one transaction. The desk already sends that pair as one grouped order.

`sendTxBatch` takes up to 50 transactions with consecutive nonces on the same API key. About 15 is safe over REST; a larger body can be rejected at the edge. The docs do not say whether a batch counts as one or as N against the 40-per-minute type limit. That is measured later, on testnet. Until then the desk does not batch.

`code: 200` means the transaction was accepted, not that it filled. The desk confirms from the account feed.

A 429 or 405 is a 60 second firewall cooldown, and a limited REST window limits the WebSocket too. Kill is never refused by the local limiter. It is sent through a full window and through that cooldown.

## Markets the desk skips

`orderBookDetails` still has two lists, perps and spot. A binary option is a row in the perp list whose `market_type` is `binary_options` (lighter-sdk 1.1.8). The desk treats that, and any other type it does not know, as not a market it trades, and leaves the row out of the book, Scan, alerts, and the Funding backfill. A missing type stays a perp, because current perp rows may omit the field. Market indexes are int64 in the signer. The desk passes them through, including indexes past 4,000. Cancel all of every market still sends `NIL_MARKET_INDEX` (255).

## Nonce

- Normal: `new_nonce = old_nonce + 1`.
- `SkipNonce` optional; cap `2^48-1`.
- API `code=200` can still advance nonce if sequencer rejects (except some maker margin failures).

## WebSocket (account / book)

- WebSocket: 200 client messages/min per IP, shared by every connection (sendTx is not in this cap; on Standard it counts in the 60/min REST bucket).
- Reconnect on deploy; chase/ladder wake on `account`, `order_book`, trades.

## COI bands (Mayedge)

| Algo | client_order_index range |
|------|--------------------------|
| Manual | `[1e9, 8e9)` |
| Advanced TWAP | `[7e9, 8e9)` |
| Chase | `[8e9, 9e9)` |
| Ladder | `[9e9, 10e9)` |
| Chase-grid | `[10e9, 11e9)` |
| Planner | `[11e9, 12e9)` |
| Trail | `[12e9, 13e9)` |

Manual and TWAP ranges overlap — known debt; ladder/chase/grid do not overlap each other.

## Errors

A send the venue refuses is classified once, in `reject_reason` (`lighter/errors.py`). The order below is the rule. A `VenueReject` keeps the reason it was built with and is never parsed again. `BudgetRefused` is the desk's own limiter and is not `BLOCKED`.

On 2026-10-21 the desk's logs for the previous 30 days had no send-reject text. The sweep matched token-icon 404s and one order-book nonce gap. Those are not fallbacks.

An `ApiException` is classified from its HTTP status and body. Headers are ignored, so `POST` or `cross-origin` cannot decide the reason.

| Order | Reason | Lighter code | Published text | Text fallback | What an algo does | Test |
|------|--------|--------------|----------------|---------------|-------------------|------|
| 1 | `BLOCKED` | HTTP 429, `23000` | Too Many Requests! | WAF / captcha / "too many requests" / "rate limit" / "ratelimit", via `venue_client_error` | cooldown, same as a venue 429 | `test_blocked` |
| 2 | `INVALID_NONCE` | `21104` | invalid nonce | "invalid nonce" | nonce cooldown, one retry in `orders.py` | `test_invalid_nonce` |
| 3 | `ORDER_NOT_FOUND` | `21701` | invalid base amount | "order not found" | cancel treats the order as gone | `test_order_not_found` |
| 4 | `MIN_SIZE` | `21706` | invalid order base or quote amount | "base or quote amount" | pause or replace; the operator sentence "Min …" is a `VenueReject`, not a phrase | `test_min_size` |
| 5 | `ORDER_CAP` | `21717`, `21718`, `21719`, `21720` | maximum active or pending order count | none | the operator sentence, then the usual unhandled path | `test_order_cap` |
| 6 | `ORDER_EXPIRY` | `21711` | invalid expiry | none | the operator sentence, then the usual unhandled path | `test_order_expiry` |
| 7 | `DUPLICATE_COI` | `21728` | client order index already exists | none | the operator sentence, then the usual unhandled path | `test_duplicate_coi` |
| 8 | `WOULD_CROSS` | `21700`, `21702`–`21705`, `21707`–`21709` | invalid order fields (the errors page has no would-cross code) | "post-only", "would cross" | keep the resting order, or wait | `test_would_cross` |

`21701` and `21706` are never `WOULD_CROSS`. Lighter publishes `21701` as invalid base amount; the desk still treats that code as order-not-found, which is what cancel already keys on. The rest of `21700`–`21709` stays would-cross, which is what the algos already did with that family. Bare "post", "cross", and "min " match nothing. A price such as `64290.5`, or an order index that merely contains a code's digits, matches nothing.

Anything `reject_reason` does not classify is logged. It is not treated as would-cross. `test_modify_nonce_is_not_a_quiet_cross` pins the grid amend that used to return on the word "post".

## Implications for ladder (keep-N)

- Default **window 10**, max **20** live rungs — fits Standard 30/market with other algos.
- Refill is **1 tx per fill** — well under 40 tx/min unless many simultaneous fills.
- Each rung must pass maker min size at plan time, at its own price: a $10 quote minimum is 500 at 0.02 but 2000 at 0.005. Checking at the touch let a ladder start whose low rungs the venue then refused.
- Would-cross rungs stay unplaced until passive (post-only + book check).
- Planner's Ladder entry rests every rung at once (no window): 2–20 rungs, and refused when its rungs plus the orders already resting on the market pass 30 ([planner-rules.md](planner-rules.md) EL4). It leaves 3 algo sends free for the stop while placing rungs.
