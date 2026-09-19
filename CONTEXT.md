# Mayedge desk

Personal Lighter perp trading desk: live markets, a chart, and execution.

## Language

### Markets

**Market**:
A Lighter-listed instrument. The desk prefers the perp when a spot twin exists.
_Avoid_: pair (for a single listing)

**Pair**:
The spot and perp Markets that share a symbol.
_Avoid_: using “pair” for “all markets”

**Daily Change**:
A Market’s 24h price change in percent points (`+3` means `+3.00%`).
_Avoid_: return, pct, 24h (unqualified)

**Numeraire**:
The Market whose Daily Change is subtracted when ranking Relative Strength. v1 is always BTC.
_Avoid_: quote, base, benchmark, index

**Relative Strength (RS)**:
A Market’s 24h excess return versus the Numeraire: Daily Change of the Market minus Daily Change of BTC. Same percent-point units. BTC versus itself is `0`. If either Daily Change is missing, RS is unknown, not `0`.
_Avoid_: RSI, ratio, beta, vs BTC price, Strength (unqualified)

**Favorites**:
Operator-pinned Markets on the header strip. Independent of Watchlist.
_Avoid_: Watchlist, stars, bookmarks

### Chart views

**Scan**:
The chart-panel view of cross-market boards (Relative Strength, liquidations). Not a price chart.
_Avoid_: RS (as a chart mode), analytics, mosaic

**Watch**:
The chart-panel view of live percent paths for a chosen set of Markets, or the same view undocked to its own window. Not Scan, not the price chart.
_Avoid_: compare, mosaic, heatmap, live (as a chart mode)

**Watch Set**:
A named Watchlist assigned to a Watch pane. Independent of Favorites.
_Avoid_: group, basket, folder, preset (unqualified)

**Watchlist**:
The Markets in a Watch Set. Cap 8. Order is add order (newest first), not Path rank, not alphabetic.
_Avoid_: Favorites, pairs, basket (unqualified), ranking by Path

**Watch pane**:
One of up to four Path charts on Watch. Each pane shows one Watch Set.
_Avoid_: tile, mosaic, widget (for a Path chart)

**Path**:
A Market’s percent change from the first sample in the visible window. Missing Last is unknown, not `0`.
_Avoid_: Daily Change, Relative Strength, return, pair (for a listing)

**Last**:
The price used to sample a Path: last trade, else mark, else mid. Missing is unknown, not `0`.
_Avoid_: close, using Daily Change as a Path sample

### Book

**Best Bid**:
The highest bid on the live book, with resting size.
_Avoid_: bid (unqualified), buy wall, ladder (for the live book)

**Best Ask**:
The lowest ask on the live book, with resting size.
_Avoid_: ask (unqualified), sell wall, offer (unqualified), ladder (for the live book)

**Top of Book**:
Best Bid and Best Ask together.
_Avoid_: using “BBO” for the price-only snapshot; mid; quote; calling the Book panel “top of book”

### Execution

**Ticket**:
An operator-placed working order on a Market. Not a Clip. Bulk side cancel pulls Tickets only.
_Avoid_: parent (unqualified), manual order, limit (for the working order itself)

**Quick size**:
The single size the floating Buy/Sell buttons and an armed price-axis rest both use.
_Avoid_: preset, clip size, ticket size (that's the Order panel)

**Clip**:
A child working order owned by an algo job. Identified by client_order_index. Not a Ticket.
_Avoid_: child (unqualified), slice (that's TWAP), rung (that's Ladder)

**Amend**:
An in-place change to a live working order’s price or size. Not cancel+replace.
_Avoid_: modify, update, replace

**Chase**:
An algo that parks one Clip behind the touch and requotes as the book walks, up to a cap.
_Avoid_: iceberg (unqualified), MM, chasing (unqualified)

**Grid**:
An algo that chases inside a price band and takes profit with reduce-only Clips. Will not start on a Market that already has another desk algo live.
_Avoid_: grid bot, DCA

**Ladder**:
An algo that keeps N live rungs on static prices.
_Avoid_: scale, iceberg, using “ladder” for the live book

**Strength**:
Size-weight skew in a Ladder plan.
_Avoid_: calling Relative Strength “strength” without “relative”

**TWAP**:
An algo that slices a parent size across time into Clips.
_Avoid_: VWAP, iceberg

**Kill**:
Emergency stop: halt algos and cancel all working orders. Flatten is optional, not implied.
_Avoid_: panic, shutdown, flatten (as a synonym for Kill)

### Account

**Account index**:
Lighter’s integer identifier for an account. Not an L1 address.
_Avoid_: wallet, L1 address, account_id (unqualified)

**Position**:
An open perp on a Market. Not an Asset.
_Avoid_: holding, balance, inventory (for the perp)

**Asset**:
A token holding on the account (USDC, ETH, …). Not a Position; not a Market.
_Avoid_: position, coin, token (unqualified), collateral (for the holding itself)

**Balance**:
An Asset’s total quantity.
_Avoid_: total (unqualified), wallet, equity

**Margin balance**:
The quantity of an Asset posted as collateral.
_Avoid_: margin (unqualified), allocated margin (that’s a Position), collateral (unqualified)

**Asset available**:
The free quantity of that Asset. Distinct from account buying power.
_Avoid_: available (unqualified), trade_available, buying power

**LTV**:
The fraction of an Asset’s index value that counts toward Portfolio Margin. Quote (USDC, USDG) is `100%`.
_Avoid_: haircut (unqualified), weight, discount

**Asset index**:
The oracle price used to value an Asset. Not Last, not Daily Change.
_Avoid_: mark, Last, index (unqualified)

**Asset uPnL**:
Unrealized PnL of an Asset versus its spot average entry at the Asset index. Quote has none. Unknown without an entry.
_Avoid_: Position uPnL, mixing into Positions

### Explorer

**Log**:
A Lighter L2 transaction, identified by `tx_hash`. Not an Ethereum transaction.
_Avoid_: blockchain (unqualified), Ethereum tx, tx (unqualified)

### Liquidations

**Long liquidation**:
A forced close of longs. Stored as `side: sell`.
_Avoid_: short squeeze, ask print (unqualified)

**Short liquidation**:
A forced close of shorts. Stored as `side: buy`.
_Avoid_: long squeeze, bid print (unqualified)

**Liquidation window**:
A 1h, 4h, or 24h lookback over persisted liquidation fills.
_Avoid_: ring, tape, cluster (the 2-minute alert window)

**Window total**:
USD of Long and Short liquidations in a Liquidation window, summed across Markets.
_Avoid_: book total, all pairs, aggregate liqs

**Liquidation intensity**:
A Market's liquidations in the window as a fraction of its open interest. Unknown if open interest is missing or 0.
_Avoid_: % OI, liq/OI
