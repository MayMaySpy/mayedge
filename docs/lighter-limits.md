# Lighter venue limits (reference)

Cross-check against official docs before changing algo behavior:

- [Rate limits](https://apidocs.lighter.xyz/docs/rate-limits)
- [Trading / signing](https://apidocs.lighter.xyz/docs/trading)
- [Data structures & errors](https://apidocs.lighter.xyz/docs/data-structures-constants-and-errors)

Last reviewed: 2026-03-11.

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

- **Standard REST:** 60 requests / rolling minute (unweighted); `sendTx` weight 6.
- **All account types — default tx bucket:** 40 requests / minute (includes order create/cancel unless Plus/Premium sendTx tiers apply).
- **429 / 23000:** backoff required; chase/ladder reuse rate-limit cooldown.

We do **not** use `sendTxBatch` today — each child is one transaction.

## Nonce

- Normal: `new_nonce = old_nonce + 1`.
- `SkipNonce` optional; cap `2^48-1`.
- API `code=200` can still advance nonce if sequencer rejects (except some maker margin failures).

## WebSocket (account / book)

- 200 client messages/min (sendTx excluded from this cap).
- Reconnect on deploy; chase/ladder wake on `account`, `order_book`, trades.

## COI bands (Mayedge)

| Algo | client_order_index range |
|------|--------------------------|
| Manual | `[1e9, 8e9)` |
| Advanced TWAP | `[7e9, 8e9)` |
| Chase | `[8e9, 9e9)` |
| Ladder | `[9e9, 10e9)` |

Manual and TWAP ranges overlap — known debt; ladder/chase do not overlap each other.

## Implications for ladder (keep-N)

- Default **window 10**, max **20** live rungs — fits Standard 30/market with other algos.
- Refill is **1 tx per fill** — well under 40 tx/min unless many simultaneous fills.
- Each rung must pass maker min size at plan time.
- Would-cross rungs stay unplaced until passive (post-only + book check).
