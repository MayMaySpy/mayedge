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

Funding in a Round trip is the funding rows on that Market with `open_ts <= ts <= close_ts`. A print on the exact close stays with the trip that closed. The next trip, even when it opens on that same timestamp, starts after it. An open Round trip takes funding from its open through the latest row.

**Net** is the venue's realized PnL, less fees, plus funding received (or less funding paid).

## Partial and open

Two Round trips are not in the headline stats. They are still listed.

- **Partial.** The first fill is older than `journal_oldest_ts`, or the replay is flat and the fill already has venue PnL. That fill closed a Position the journal never saw open. It does not also open a new one: the journal cannot see how much of it was a flip. `partial` says which of the two it was.
- **Open.** The Market is not flat yet. `open` is true. uPnL is the live Position's, passed in by the caller. It is not part of Net.

## Algo and R

Each fill may name an `algo_id` (`PL-`, `CH-`, `CG-`, `LD-`, `TW-`, `TR-`). The Round trip's algo is the family with the most opening size. No linked opening size means `manual`.

**R** is Net divided by `|entry − stop| × size`. Entry and stop are the plan stored on that Planner run when it started (`plan.entry`, `plan.stop`), and size is the size this Round trip opened. A Planner run with no stored stop, a zero risk, or any other family has no R.

## Summary

Headline stats use closed Round trips that are not partial.

Per group (`day`, `market`, `algo`, or `none`): count, wins, losses, win rate, gross PnL (the venue number), fees, funding, Net, average win, average loss, profit factor, expectancy (Net per Round trip), largest win, largest loss, maker share of notional, and average and total R where a trip has one.

A day is the UTC date of the close. Win rate is wins divided by wins plus losses. Profit factor is the winning Net divided by the absolute losing Net. No losing Round trip means profit factor is absent, not infinite. No Round trips means the rates are absent.

`none` also returns the realized Net curve, one point per close, and the largest peak-to-trough drop of that curve in dollars.

## Sync

Sync pages the venue newest first, 100 a page, and stops at the first page that already contains a stored `trade_id`. Funding pages the same way. Each page waits for the shared REST budget and then yields. Writes are `INSERT OR IGNORE`.

Nothing syncs when trading is off. The first backfill runs as far as the venue still has rows, and the oldest timestamp reached is `journal_oldest_ts`. After boot, sync waits 30 seconds, then repeats every 5 minutes, and again 10 seconds after the account feed reports a fill.
