# Mayedge desk

Personal Lighter perp trading desk: live markets, a chart, and execution.

## Language

**Market**:
A Lighter-listed instrument. The desk prefers the perp when a spot twin exists.
_Avoid_: pair (for a single listing)

**Pair**:
The spot and perp Markets that share a symbol.
_Avoid_: using “pair” for “all markets”

**Daily Change**:
A Market’s 24h price change in percent points (`+3` means `+3.00%`).
_Avoid_: return, pct, 24h (unqualified)

**Strength**:
Size-weight skew in a ladder plan.
_Avoid_: calling Relative Strength “strength” without “relative”

**Numeraire**:
The Market whose Daily Change is subtracted when ranking Relative Strength. v1 is always BTC.
_Avoid_: quote, base, benchmark, index

**Relative Strength (RS)**:
A Market’s 24h excess return versus the Numeraire: Daily Change of the Market minus Daily Change of BTC. Same percent-point units. BTC versus itself is `0`. If either Daily Change is missing, RS is unknown, not `0`.
_Avoid_: RSI, ratio, beta, vs BTC price

**Scan**:
The chart-panel view of cross-market boards (Relative Strength, liquidations). Not a price chart.
_Avoid_: RS (as a chart mode), analytics, mosaic

**Best Bid**:
The highest bid on the live ladder, with resting size.
_Avoid_: bid (unqualified), buy wall

**Best Ask**:
The lowest ask on the live ladder, with resting size.
_Avoid_: ask (unqualified), sell wall, offer (unqualified)

**Top of Book**:
Best Bid and Best Ask together.
_Avoid_: using “BBO” for the price-only snapshot; mid; quote; calling the Book panel “top of book”

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
