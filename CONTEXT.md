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

### Alerts

The rules are in [docs/alert-rules.md](docs/alert-rules.md).

**Alert**:
A row the desk raises for the operator to act on by feel: a Spike, Liquidations, a Board move, or Near liquidation. It states a fact. It does not say what comes next.
_Avoid_: signal, setup, Tone alert

**Spike**:
A minute at least N times the biggest minute of the last hour, in price, volume or open interest. The biggest minute of the hour is not a Spike.
_Avoid_: outlier, sigma, surge, unusual

**Day range**:
A Market's 24h high less its 24h low, in percent of the low, as the venue prints them.
_Avoid_: ATR, volatility, sigma

**Broad move**:
The median 5m move of the liquid perps going the same way, when at least ten are and they are most of the perps that moved. One row, named Market.
_Avoid_: Relative Strength, BTC, the market (unqualified), the median of all perps

**Excess move**:
A Market's move less the Broad move, while one is on and the Market goes the same way. The part the rest of the board does not explain.
_Avoid_: alpha, Relative Strength, beta, residual (unqualified)

**Held market**:
A Market with a Position or a working order on it. Every alert on it raises a toast.
_Avoid_: Favorites, Watchlist, exposure

**Funding strip**:
The line above the alerts naming every Market whose funding is far from its own day. It says an extreme exists. It raises nothing.
_Avoid_: funding alert, Crowded longs, Crowded shorts

**Left**:
The furthest the price went an alert's way in the 15 minutes after it, from the price it fired at.
_Avoid_: Follow-through, hit rate, PnL, return

**Against**:
The furthest the price went the other way in the same 15 minutes.
_Avoid_: drawdown, stop, loss

**Opened**:
An alert the operator opened from the panel. The count of these is how the desk learns which alerts were worth raising.
_Avoid_: clicked, viewed, read

**Push**:
A Telegram message the desk sends the operator. It repeats a fact; it raises nothing new.
_Avoid_: notification, alert (for the message itself)

### Chart views

**Scan**:
The chart-panel view of cross-market boards (Relative Strength, liquidations, Activity, Tones). Not a price chart. Nothing on it alerts.
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

**Timeframe**:
The bar size of the price chart.
_Avoid_: interval, resolution, candle size

**Pinned timeframe**:
An operator-chosen Timeframe on the price chart. Cap 7. The active Timeframe may be unpinned.
_Avoid_: Favorites, stars, bookmarks

**MayRekt**:
Candle coloring on the price chart. One Tone per bar, or none. Runs on the bars that chart already shows, including the forming bar.
_Avoid_: indicator, Pine, signal, overlay, study

**Tone**:
The named color of one candle under MayRekt. Absent when the bar has no state.
_Avoid_: barcolor, signal, alert

**Activity**:
The Scan board of every liquid perp and what its tape shows now: the 5m move and its share of the Day range, volume, open interest, funding and premium.
_Avoid_: Live, outliers, signals

**Tones board**:
The Scan board of liquid perps whose last closed bar on a Tone timeframe is blue or orange. The forming bar is never on it.
_Avoid_: Tone alert, signal

**Tone timeframes**:
The native Timeframes the Tones board follows. At most two. Default is 30m and 4h.
_Avoid_: Pinned timeframe, the chart's Timeframe

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

**Notional**:
Size times the working price on a Ticket: the limit price when set, otherwise mid, live side, or last. The ticket may be typed in the asset or in USD; the order still goes out in Size.
_Avoid_: USD size, value, quote size (that's the venue minimum)

**Stop**:
A reduce-only Ticket that closes all or part of a Position when mark hits the trigger. Market or Limit. Not a Clip.
_Avoid_: SL (in prose), stoploss, protective stop

**Take Profit**:
A reduce-only Ticket that closes all or part of a Position when mark hits the trigger on the profitable side. Market or Limit. Not a Clip. Not Grid’s reduce-only Clips.
_Avoid_: TP (in prose), target (unqualified)

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

**Planner**:
An algo that runs one trade from the stop out: it sends the entry (or takes over an open Position), places the stop and targets as Clips, and takes a Stop step as targets fill. It owns the exit on its Market. The rules are in [docs/planner-rules.md](docs/planner-rules.md).
_Avoid_: Planer, bracket, OCO, setup

**Draft**:
A Planner drawn on the chart before it exists: entry, stop and targets, with no orders behind them. One per Market, in memory only. Nothing reaches the venue until Start in the Planner dialog.
_Avoid_: plan (unqualified, that's the algo), ghost order, bracket

**R**:
The distance from a Planner's entry to its stop, in price. Targets, risk and size are all measured in it. One stop, one R. A Round trip's R is its Net divided by the risk at that stop when it opened. Only Planner Round trips have one.
_Avoid_: risk unit (unqualified), ATR, a second "suggested" stop, RR, risk-reward (for the result)

**Breakeven**:
A Planner stop moved to entry plus round-trip fees, so closing there loses nothing.
_Avoid_: BE (in prose), entry (as the stop price)

**Stop step**:
A move of a Planner's stop toward profit when a target fills: to Breakeven after TP1, and with Step up to each earlier target's price after the next one fills. Proven by the fill, never by time or price alone.
_Avoid_: trail (that's a **Trail**), trailing stop, ratchet

**Runner**:
The part of a Planner Position no target closes. It rides on the stop until the Position closes.
_Avoid_: remainder (unqualified), moonbag, trail (that's a **Trail**)

**Trail**:
A desk algo that keeps a trigger a set distance behind the **best price** and fires when price comes back by that distance. It is an Entry, a Stop or a Take Profit. Its orders are Clips, not Tickets. It follows only while the desk is running. The rules are in [docs/trail-rules.md](docs/trail-rules.md).
_Avoid_: trailing stop (unless it is a Stop), TSL, ratchet, Stop step (that's Planner's move on a target fill)

**Best price**:
The most favourable price of a Trail's Reference since activation: the highest for a long exit or a short entry, the lowest for a short exit or a long entry.
_Avoid_: high-water mark, HWM, peak, high (that's a candle's high)

**Trail distance**:
How far a Trail's trigger stays behind the best price: a %, or a price distance.
_Avoid_: offset, callback

**Activation**:
The price a Trail must reach before it starts following. Until then it waits. "Trigger" stays the word for the venue's trigger price.
_Avoid_: trigger (for this), arm price

**Reference**:
What a Trail follows: Mark, or Last (each public trade print).
_Avoid_: source, price type

**Backstop**:
The venue Stop a Trail on Last keeps one step behind its trigger, so the exit holds while the desk is down.
_Avoid_: safety stop, hard stop

**Kill**:
Emergency stop: halt algos and cancel all working orders. Flatten is optional, not implied. Each step is sent whatever the one before it did, and none waits on the rate budget.
_Avoid_: panic, shutdown, flatten (as a synonym for Kill)

### Account

**Account index**:
Lighter’s integer identifier for an account. Not an L1 address.
_Avoid_: wallet, L1 address, account_id (unqualified)

**Position**:
An open perp on a Market. Not an Asset.
_Avoid_: holding, balance, inventory (for the perp)

**Round trip**:
A Position in one Market from flat to flat. A flip ends one Round trip and starts the next at the same fill.
_Avoid_: trade (a Lighter trade is one fill), position (that is the live thing)

**Net**:
Realized PnL less fees, plus funding received (or less funding paid).
_Avoid_: PnL (unqualified), equity, a limit for Auto kill

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

**Liquidation threshold**:
The fraction of an Asset’s index value that counts when deciding if the account is liquidated. At least the LTV. Quote is `100%`.
_Avoid_: LTV, Portfolio Margin

**Liquidation price**:
The price of a cross Position at which the account, valued with each Asset’s Margin balance at its Liquidation threshold, meets maintenance margin.
_Avoid_: Last, entry, a leverage estimate, the venue mark

**Asset index**:
The oracle price used to value an Asset. Not Last, not Daily Change.
_Avoid_: mark, Last, index (unqualified)

**Asset uPnL**:
Unrealized PnL of an Asset versus its spot average entry at the Asset index. Quote has none. Unknown without an entry.
_Avoid_: Position uPnL, mixing into Positions

### Portfolio

The rules are in [docs/portfolio-rules.md](docs/portfolio-rules.md).

**Portfolio**:
Everything the account holds on Lighter, valued in USD: Perps, Spot, LLP and Staking.
_Avoid_: balance, equity, TAV (TAV is the Perps part)

**Holding**:
One part of the Portfolio. Its kind is Perps (USDC collateral plus open uPnL), Spot (assets, held or used as collateral), LLP (shares in the Lighter liquidity pool) or Staking (LIT in the staking pool). Pending unlocks are listed with their date.
_Avoid_: position (that is a perp), asset (that is a spot balance)

**Flow**:
Money moved into or out of a Holding: a deposit, a withdrawal, a transfer between Perps and Spot, joining or leaving LLP, staking or unstaking. A Flow is not a gain.
_Avoid_: transfer (one kind of Flow), PnL

**Day open**:
When the Portfolio's day starts: 00:00 UTC. The desk does not use local time.
_Avoid_: local midnight, 00:00 (unqualified), session open

**Day change**:
A Holding's cumulative PnL now less at the Day open. Its value moved by that much plus its Flows.
_Avoid_: 24h change, return

### Open interest

**Open interest**:
The two-sided USD open interest of a perp: long plus short. The venue prints one side; the desk uses twice that. Spot has none.
_Avoid_: one-sided OI, base size, resting size

**OI sample**:
A perp's open interest at the end of a UTC minute. Kept for 30 days.
_Avoid_: tick, trade, candle

**OI hour**:
A perp's high, low, and last open interest for one UTC hour older than 30 days. Kept for the life of the desk. Last is the final sample of that hour. 1h, 4h and 1d charts read OI hours past 30 days; 1m-15m charts stop at 30 days.
_Avoid_: OI day, sum, Liquidation day, candle

### Funding

**Funding estimate**:
The venue's 1h funding rate for the hour in progress. It moves until the hour settles. Sampled each UTC minute and kept for 30 days.
_Avoid_: funding print, paid rate

**Funding print**:
The 1h rate a perp settled for one hour, filed under the hour it paid for. Kept for the life of the desk.
_Avoid_: funding estimate, funding sample

**Funding backfill**:
Funding prints, then Funding days, for the last year, read from the venue's funding history once per perp. The venue keeps about 62 days of hours. Each writes only when the venue's latest rows match the desk's own Funding prints under one reading, and never replaces a print the desk recorded live.
_Avoid_: import, sync

**Funding day**:
A perp's mean 1h funding rate for one finished UTC day, from the venue's daily history. Used only for a day without all 24 Funding prints. Kept for the life of the desk. Never fills an hourly or 4h bucket.
_Avoid_: daily print, day sum

**Funding average**:
The mean of a perp's Funding prints over 7 days, 30 days, or a year, in APR. A Funding day counts as 24 hours. A window named by its length holds at least 95% of its hours; a shorter history is named by the span it holds.
_Avoid_: average estimate, mean funding (unqualified)

**Fund pane**:
The chart pane of a perp's funding in APR, one bar per bucket. A bucket with Funding prints is their mean; a 1d bucket short of 24 prints shows its Funding day. A bucket with none shows the last Funding estimate in it, drawn faint.
_Avoid_: funding line, funding alert

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
A 1h, 4h, 24h, 7-day, or 30-day lookback. Each liquidation in that span is still a fill.
_Avoid_: ring, tape, cluster (the 2-minute alert window)

**Liquidation day**:
A Market's long USD, short USD, total, and largest liquidation for one UTC day older than 30 days. Kept for the life of the desk. Fills of one taker order stay on the day that liquidation started.
_Avoid_: candle, bucket, archive

**Window total**:
USD of Long and Short liquidations in a Liquidation window, summed across Markets.
_Avoid_: book total, all pairs, aggregate liqs

**Window share**:
A Market's liquidations in the window as a fraction of Window total.
_Avoid_: Liquidation intensity, vs OI

**Largest liquidation**:
The single biggest liquidation on a Market inside a Liquidation window, in USD. Fills from one taker order are one liquidation.
_Avoid_: largest fill, max print

**Liquidation intensity**:
A Market's liquidations in the window as a fraction of its open interest. Unknown if open interest is missing or 0.
_Avoid_: % OI, liq/OI

### Desk history

**Backup**:
A compressed copy of the desk database taken while the desk runs, kept on the host outside Docker.
_Avoid_: snapshot, dump, export

**Loop lag**:
How late the desk's event loop ran a timer it set, in ms. Above 250 ms the desk is late on everything at once.
_Avoid_: latency, lag (unqualified)

**Send budget**:
The desk's share of Lighter's per-minute limits: requests and transactions in the last 60 seconds, against the desk's own caps.
_Avoid_: rate limit (for the desk's share), quota
