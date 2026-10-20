# Journal rules

History is one fill at a time. A **Round trip** is that Market from flat back to flat. The journal stores fills, funding, and notes. It rebuilds Round trips on read, so a rule change does not migrate old rows.

The rules below are what `journal.py` does. Nothing here adds a realized-PnL or equity limit to Auto kill.

## Fills

A fill is the venue row: side (`buy` or `sell` from this account), price, size, fee, the venue's realized PnL, and whether it was maker. Timestamps may be seconds or milliseconds; a value above `10^12` is milliseconds.

Replay each Market on its own, from flat, in timestamp order. The same timestamp breaks ties by `trade_id`.

- A buy adds to a long. A sell adds to a short. Either one opens when the Market is flat and the venue PnL is zero.
- Adding while a Position is already open scales in. The fee stays on that Round trip.
- A fill against the open Position closes it, up to the open size. Realized PnL is the venue's `pnl` on that closing fill. The journal does not recompute it. Average entry and average exit are only a check in tests.
- A fill that crosses zero is split at zero. The closing part ends the old Round trip. The rest opens the next one, at the same price and timestamp. The fee and the notional are shared in proportion to size. The venue PnL stays on the closing part.
- The side of a Round trip is `long` or `short`, from the opening fills. Size is the size that opened it. Average in and average out are size-weighted.

## Funding

Funding in a Round trip is the funding rows on that Market with `open_ts <= ts <= close_ts`. The venue stamps fills in milliseconds and funding in seconds, so both are compared in seconds. A print on the exact close stays with the trip that closed. The next trip, even when it opens on that same timestamp, starts after it. An open Round trip takes funding from its open through the latest row.

**Net** is the venue's realized PnL, less fees, plus funding received (or less funding paid).

## Partial and open

Two Round trips are not in the headline stats. They are still listed.

- **Partial.** The first fill is older than `journal_oldest_ts`, or the replay is flat and the fill already has venue PnL. That fill closed a Position the journal never saw open. It does not also open a new one: the journal cannot see how much of it was a flip. `partial` says which of the two it was.
- **Open.** The Market is not flat yet. `open` is true. uPnL is the live Position's, passed in by the caller. It is not part of Net.

## Algo and R

Each fill may name an `algo_id` (`PL-`, `CH-`, `CG-`, `LD-`, `TW-`, `TR-`). The Round trip's algo is the family with the most opening size. No linked opening size means `manual`. The algo filter takes a family, `manual`, `algos` (every family except manual), or nothing for every Round trip.

**R** is Net divided by `|entry − stop| × size`. Entry and stop are the plan that Planner run holds (`plan.entry`, `plan.stop`): the actual average entry once it filled (planner-rules P1), and the stop it was planned with. A Re-plan replaces that stop; Stop steps and a Trail stop do not. Size is the size this Round trip opened. A Planner run with no stored stop, a zero risk, or any other family has no R.

## Summary

Headline stats use closed Round trips that are not partial.

Per group (`day`, `market`, `algo`, or `none`): count, wins, losses, win rate, gross PnL (the venue number), fees, funding, Net, average win, average loss, profit factor, expectancy (Net per Round trip), largest win, largest loss, maker share of notional, and average and total R where a trip has one, with `r_count`, how many do.

A day is the UTC date of the close. Win rate is wins divided by wins plus losses. Profit factor is the winning Net divided by the absolute losing Net. No losing Round trip means profit factor is absent, not infinite. No Round trips means the rates are absent.

Every group also carries what a trader asks of a record without a plan, all from Net:

- **Payoff** is average win over the absolute average loss. **Breakeven win rate** is `1 / (1 + payoff)`: the win rate that payoff needs to make nothing. Either is absent without both a win and a loss.
- **Notional** is the traded USD of every fill. **Net per $ traded** is Net over notional, in basis points: an edge that does not grow with size.
- **Streaks** run in close order: the longest run of wins, of losses, and the run now (`+3` three wins, `-2` two losses). A Round trip with Net exactly 0 is skipped, not a break.
- **Hold** is the average seconds from open to close, for winners and for losers apart.
- **Long** and **short**: count, win rate and Net of each side.
- **Days** group by UTC close date: how many days closed a Round trip, how many of those were green, the best and the worst day's Net.

`none` also returns the realized Net curve, one point per close, and the largest peak-to-trough drop of that curve in dollars. **Recovery factor** is Net over that drop.

The desk tab shows one row: Net, win rate (with its breakeven), profit factor, payoff, expectancy, max drawdown, the streak now, and funding. The page groups the rest by edge, risk, wins and habits. **R stays a Planner number**: it shows only on the page, labelled with how many of the Round trips it covers, and never stands in for the whole record. Fees show only when they are not zero.

## Sync

Sync pages the venue newest first, 100 a page, and stops at the first page that already contains a stored `trade_id`. Funding pages the same way. That stop applies only once a walk has reached the venue's oldest page (`journal_backfilled_trades`, `journal_backfilled_funding`). Until then a sync walks past stored rows, so a first backfill cut short by the budget or the network is finished by a later sync instead of leaving a hole. Each page waits for the shared REST budget and then yields. Writes are `INSERT OR IGNORE`.

Nothing syncs when trading is off. The first backfill runs as far as the venue still has rows, and the oldest timestamp reached is `journal_oldest_ts`. After boot, sync waits 30 seconds, then repeats every 5 minutes, and again 10 seconds after the account feed reports a fill.
