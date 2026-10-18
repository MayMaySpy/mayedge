# Trail: scope (draft 2)

Scope for trailing orders on the desk: as an entry, as a stop, as a take profit, and inside Planner. **Built on 2026-10-18.** The rules now live in [trail-rules.md](trail-rules.md) and [planner-rules.md](planner-rules.md) (E9, M10, M11, P9), and the decision in [ADR 0016](adr/0016-a-trail-is-moved-by-the-desk.md). Every open question in §9 went with the lean given there. Phase 0: Lighter's docs say triggers fire on mark. Nobody has checked whether an opening Stop works, so entries stay desk-held. This file is kept for the reasoning; where it and the rules differ, the rules win.

Words in bold mean what [CONTEXT.md](../CONTEXT.md) says they mean.

## Decided (2026-10-18)

1. A Trail can **enter** as well as exit.
2. A Trail is not only a stop. It is a general **Stop or Take Profit**. In Planner, the Runner (what's left after TP1/TP2/…) can trail on its stop, and a target can itself be a trailing take profit.
3. Every Trail can have an **Activation** price: it trails only once price reaches X. The standalone trailing entry has one too.
4. A Trail follows **Mark** or **Last**, the operator's choice.

## 1. What the venue gives us

- **No trailing order type.** Lighter's types are 0–6: Limit, Market, Stop Loss, Stop Loss Limit, Take Profit, Take Profit Limit, TWAP. So a Trail is a desk algo that moves a real order, or fires one itself.
- **Venue triggers fire on mark.** The desk's own trigger checks assume this (`_check_trigger_side` reads mark). Confirm it in the Lighter docs in phase 0.
- **An opening Stop might be possible.** The SDK's `create_sl_order` takes `reduce_only=False`. Nobody has checked whether Lighter accepts a non-reduce-only Stop Market that opens a Position. Check in phase 0, at minimum size, by hand (this is mainnet).
- **Rate:** 40 tx a minute. Algos hold to 30 of the 38 the desk lets itself use ([lighter-limits.md](lighter-limits.md)). Pending trigger orders: 10 per Market on Standard.

That gives two ways a Trail can hold its trigger:

| | Venue-held | Desk-held |
|---|---|---|
| What sits on Lighter | a Stop Market, its trigger moved by Amend | nothing, or a backstop |
| Who fires it | the venue, on mark | the desk, which sends a Market order when the reference crosses |
| While the desk is down | stays at the last trigger and fires there | does not fire |
| Used for | exits on Mark | every entry, and exits on Last (with a venue backstop) |

The property to design around, and to say plainly in the UI:

> **A Trail follows only while the desk is running.** When the desk is down, an exit's stop holds at the last price it was moved to, and an entry or an un-activated Trail waits.

Each of these fails safe. An exit never loosens, and an entry never fires on a level nobody is watching.

## 2. Language (proposed CONTEXT.md entries)

**Trail**:
A desk algo that keeps a trigger a set distance behind the **best price** and fires when price comes back by that distance. It is an **Entry**, a **Stop** or a **Take Profit**. Its orders are Clips, not Tickets. It follows only while the desk is running.
_Avoid_: trailing stop (unless it is a Stop), TSL, ratchet, Stop step (that is the move Planner makes on a target fill)

**Best price**:
The most favourable price of the chosen reference since activation. For an exit on a long, or an entry on a short, that is the highest. For an exit on a short, or an entry on a long, it is the lowest.
_Avoid_: high-water mark, HWM, peak, high (that is a candle's high)

**Trail distance**:
How far the trigger stays behind the best price: a %, a price distance, or (in Planner) a multiple of **R**.

**Activation**:
The price a Trail must reach before it starts following. Until then it waits. "Trigger" stays the word for the venue trigger price.
_Avoid_: trigger (for this), arm price

**Reference**:
What a Trail follows: **Mark**, or **Last** (each trade print).

## 3. The three kinds

All three share the same inputs: side, size, Activation (optional, except on a Take Profit), distance, Reference, and execution (Market with the ticket's slippage, capped at 5%).

### 3.1 Trail Entry (opens or adds)

A long entry tracks the **lowest** price, and buys when price rises the distance off it. A short entry tracks the highest, and sells.

| # | Rule |
|---|---|
| TE1 | It is desk-held: the desk sends a Market order when the reference crosses the trigger. While the desk is down it does not fire (see Q1 for the venue-held option). |
| TE2 | With an Activation, it starts tracking only once the reference reaches that price. A long waits for the dip to X, a short for the pop to X. Without one, it tracks from start. |
| TE3 | Trigger = lowest price + distance for a long, highest − distance for a short. It moves only toward the better entry. |
| TE4 | An optional expiry ends it unfilled. |
| TE5 | It fills with a Market order at the slippage cap. A fill counts only with evidence from trades or the account feed ([ADR 0003](adr/0003-invent-fill-needs-evidence.md)). |
| TE6 | A standalone entry is bare, like a Ticket. It places no stop. A trailing entry with a stop and targets is a Planner with a Trail entry (§5.1). |

### 3.2 Trail Stop (protects a Position)

| # | Rule |
|---|---|
| TS1 | It goes on the venue at a start price at once. The Position is protected from the first second. |
| TS2 | Without an Activation it trails from start. With one, the stop holds at its start price until the reference reaches the Activation price, then trails. |
| TS3 | Trigger = best price − distance for a long, + for a short. It only moves toward profit. Nothing moves it back, not even a new distance. |
| TS4 | It covers the whole Position: size 0, tied to the Position, so adds and partial closes need no Amend. |
| TS5 | It replaces the Market's Stop Tickets. Its stop goes on first, then they come off, and the confirm names each one. There is one stop per Position (same reasoning as [ADR 0015](adr/0015-planner-owns-the-exit.md)). |

### 3.3 Trail Take Profit (closes in profit)

| # | Rule |
|---|---|
| TT1 | Activation is required and is on the profit side. Until it is reached, nothing is on the venue. |
| TT2 | When the reference reaches the Activation price, it places a reduce-only Stop Market at best price − distance, and trails from there. |
| TT3 | Size is a % of the Position, or all of it. |
| TT4 | It sits beside the Position's Stop, whether that is a Ticket or a Trail Stop, and beside Take Profit Tickets. Every leg is reduce-only, so they cannot over-close. |
| TT5 | It does not activate while the desk is down. A plain Take Profit Ticket does work then, and the UI says so. |

### 3.4 Shared by every kind

| # | Rule |
|---|---|
| T1 | It moves only when the new trigger beats the current one by at least **step**, and no sooner than **min gap** after the last move (§6). |
| T2 | Prices round to the tick, the safe way: an exit's trigger away from mark, an entry's toward a worse fill. |
| T3 | The best price, activation state and trigger are saved with the algo run. A restart picks up where it left off. The desk does not rebuild what it missed while it was down (Q7). |
| T4 | If a venue-held stop leaves the book while the Position is open, the desk puts it back. If price is already through it, the desk closes with a reduce-only Market (as Planner E8 does). |
| T5 | If an Amend is refused as "wrong side of mark", the trigger stays where it is. Price is already through it, so it is about to fire. |
| T6 | **Kill**, or Cancel all on its Market, stops every Trail there and cancels its orders. |
| T7 | Its Clips use their own client_order_index band, `[12e9, 13e9)` ([ADR 0004](adr/0004-partitioned-client-order-index.md)). |
| T8 | It refuses beside a Planner (Planner runs its own Trails, §5) and beside Grid ([ADR 0002](adr/0002-grid-is-exclusive-on-a-market.md)). |
| T9 | Per Market at once: at most one Trail Entry, one Trail Stop, and three Trail Take Profits (Q5). |
| T10 | The chart draws its lines but does not let you drag them ([ADR 0007](adr/0007-chart-amends-tickets-only.md)). |

## 4. Mark or Last

| | Mark | Last |
|---|---|---|
| Best price from | mark, from market stats | every public trade print, so it catches wicks |
| Entry | desk-held | desk-held |
| Exit | venue-held: the Stop Market trigger is moved by Amend | desk-fired on Last, with a venue **backstop** |

**Exits on Last.** The venue fires only on mark, so the desk watches Last and sends a reduce-only Market when a print goes through the trigger. A venue Stop Market sits **one step behind** the trigger as a backstop. It covers the desk being down, and it is far enough back that mark rarely gets there first. Once the desk's close fills, the desk cancels the backstop. If both fire anyway, both are reduce-only. A Trail sized to the whole Position can't over-close. A partial one could close up to twice its size; the confirm says so (Q2).

**Trades feed.** Today the gateway subscribes to trades only for the Market on screen (`skip_idle_trade` drops the rest). A Trail on Last must keep its own Market's trade subscription for as long as it runs. If that feed goes stale, the Trail stops following, shows `not following`, and its backstop stays where it is.

## 5. In Planner

### 5.1 Trail as an entry type

Entry type becomes **Market, Limit, or Trail** (Enter mode only).

- It takes the Trail Entry inputs: Activation, distance (% or price), Reference.
- **R and size are worked out when it fires.** Before that, the plan shows R and size at the current trigger, marked "at the trigger now". When it fires, size = equity × risk % ÷ (trigger − stop + fees), so the risk stays as planned and the size floats. This changes P2: "fixed once sent" becomes "fixed when the entry is sent, and for a Trail entry, sent means fired".
- S1 is checked at start, and again at fire, against the trigger. If the best price falls through the stop while it is tracking, the entry is cancelled. That is E4 as it stands.
- E3 onward is unchanged: the stop goes on with the first fill, and targets are drawn from the actual entry (P4).

### 5.2 Runner trail (the stop trails what's left)

New input: **Trail the stop**, with the options Off, After TP*n*, After the last target, or At *n*R. Distance is in R or %.

```
stop = further of (stepped stop, best price − trail distance)
```

Stop steps (Breakeven / Step up) keep doing what they do now. Once the trail starts, it can only tighten the stop. "After TP1" trails everything left after TP1, "After the last target" trails the Runner alone, and "At 2R" trails before any target fills.

### 5.3 Trail as a target type

A target's order is **Limit, Trigger, or Trail**:

- Its price (or R) is the **Activation**. The target's own trail distance (R or %) sets how far the trigger stays behind.
- When the reference reaches that price, Planner places a reduce-only Stop Market for that target's % and trails it (TT2).
- It "fills" when that stop fills. M2 (Stop step on a full fill) applies at that point.
- With Step up, the step after a Trail target goes to its **fill price**, not its Activation price (Q3).

### 5.4 Planner dialog

```
Entry        [ Market | Limit | Trail ]
  Trail      activate at [ 2.1000 ]  (optional)   distance [ 1 ] [ % | price ]
             Follows [ Mark | Last ]

Targets      TP1  2R   30%  [ Limit | Trigger | Trail ]
             TP2  3R   30%  [ Trail ]  distance [ 0.5 ] [ R | % ]
Stop steps   [ Off | Breakeven | Step up ]
Trail stop   [ Off | After TP1 | After last | At R ]   distance [ 1 ] [ R | % ]

Waits for 2.10, then buys when Last bounces 1% off the low.
After TP1, the stop follows 1R behind the best price, never below Breakeven.
TP2 activates at 3R and closes 30% once price gives back 0.5R.
⚠ Trail parts follow only while the desk is running.
```

The Reference is one setting per plan.

### 5.5 Rule changes to planner-rules.md

| Rule | Change |
|---|---|
| Inputs | Entry type gains Trail. Target type gains Trail. New: Trail stop, Trail distance, Reference. |
| P2 | A Trail entry is sized when it fires (§5.1). |
| P5 | "It rides on the stop" → "on the stop, which may trail". |
| P9 | Add the Trail target (§5.3). |
| E1 | Add: a Trail entry is desk-held and fires as a Market order. |
| M2 | A Trail target counts as filled when its stop fills. Step up after it goes to its fill price. |
| M4 | "Stop steps are the only moves" → "Stop steps and the Trail stop are the only moves. The stop is the further of the two, and each moves only toward the winning side." |
| new M10 | Trail stop follows the best price from its start (§5.2). |
| new M11 | A paused Planner (M6) does not trail or activate. On resume it carries on from the best price it saved. |
| M5 | A re-plan may change Trail settings. A new distance never moves a live trigger back. |
| M7 | Add: trails hold while the desk is down. A Trail target that has not activated waits, unlike a Trigger target. |
| Later | Remove "Trailing the Runner (v2)". |

### 5.6 Code touch points

- `planner/plan.py`: `PlannerParams` gains the entry Trail settings, `trail_stop`, the Reference, and a per-target `order="trail"` with its distance. `price_plan` resolves R distances to prices.
- `planner/state.py`: saves the best price for each part that trails, and which ones have activated.
- `planner/job.py`: `_evaluate_entry` gets a Trail branch. `_evaluate_manage` runs `_take_step()`, then the Trail stop, then the Trail targets. All of them use the shared engine and the existing `amend_trigger_leg` / M9 path.
- Web: `PlannerDialog.tsx` and `PlannerRow.tsx`.

## 6. Engine and rate budget

One pure function, used by every kind and by Planner:

```
step_trail(kind, side, ref_price, state{best, active, trigger}, params{activation, distance, step, floor}, tick)
  -> state', action: none | amend(trigger) | place(trigger) | fire
```

| Knob | Default | Why |
|---|---|---|
| min gap per Trail | 5s | At most 12 Amends a minute from one Trail, even in a straight-line move. |
| step | max(10% of the distance, 2 ticks) | Gives back at most one step against an ideal trail. |
| per Market | 15 Amends a minute across all its Trails | A Planner with a trailing stop and two Trail targets still fits inside the algo lane's 30. |
| fire / close | never held back by the gap | An exit or entry that is due goes now. |
| BudgetRefused / 429 | keep the trigger, back off 2s | Same as Planner. The stop is already on the venue. |

These live in code config, not the UI.

## 7. UI/UX

### 7.1 Order ticket: Trail Entry

A new ticket kind, **Trail**, beside Limit, Market, Chase, Ladder, TWAP and Grid (`orderTicket/kinds/TrailParams.tsx`). Buy/Sell and size come from the ticket.

```
Kind        Limit  Market  Chase  Ladder  TWAP  [Trail]
Size        525 ZRO   ($1,150)
Activate at [ 2.1000 ]  optional: wait for this first
Distance    [ 1.0 ] [ % | price ]
Follows     [ Mark | Last ]
Expiry      [ 60 ] min
▸ Advanced  step · slippage 1%

Waits for ZRO at or below 2.1000. Then buys 525
when Last bounces 1% off the lowest print.
If the low is 2.0500, it buys at about 2.0705.
⚠ Fires only while the desk is running.
                                        [ Buy Trail ]
```

### 7.2 Positions row: Stop and Take Profit get a Trail mode

There is no new tab. The existing Stop and Take Profit tabs in `PositionProtectPopover` each get a **Fixed | Trail** switch, so a Trail is a kind of stop or take profit, not a separate thing.

```
Stop     [ Fixed | Trail ]
  Starts at   [ 2.0854 ]
  Activate at [ 2.2500 ]  optional
  Distance    [ 1.5 ] [ % | price ]   Follows [ Mark | Last ]
  Stop now 2.0854. From 2.2500 it stays 1.5% behind the best price.
  Replaces 1 Stop Ticket @ 2.0800.

Take Profit [ Fixed | Trail ]
  Activate at [ 2.4000 ]  required
  Distance    [ 1.0 ] [ % | price ]   Size [ 50 ] %
  At 2.4000 it starts following, and closes 50% after a 1% pullback.
  Does not activate while the desk is down.
```

The validation is inline: a distance under a few ticks, an Activation price on the wrong side, a start price past the **Liquidation price**.

### 7.3 Working rows (algo blotter)

```
Trail Entry  ZRO buy 525    1% Last   waiting for 2.1000                       [Edit] [Stop]
Trail Stop   ZRO long       1.5% Mark stop 2.3640  best 2.4000  moved 14s ago  [Edit] [Stop ▾]
Trail TP     ZRO 50%        1% Last   following  best 2.4410  fires 2.4166     [Edit] [Stop]
```

- The states are `waiting`, `following`, `firing`, and `not following` (amber: a stale feed or rate backoff, with the reason on hover).
- On a Trail Stop, **Stop ▾** offers **Keep stop** (default: a plain Stop Ticket goes on at the current trigger, then the Clip comes off) or **Cancel stop** (says the Position is left with no stop).
- On a phone, rows wrap after the symbol, the same as Planner's target rows.

### 7.4 Chart

- An Entry Trail draws a dashed line at its trigger and a marker at the Activation price.
- Exits draw their stop or trigger line, labelled `Trail 1.5%`: dashed while waiting, solid while following.
- A tick on the price axis marks the best price.
- None of these drag. Clicking one opens Edit.

### 7.5 Kill dialog

It warns while a Trail Stop is live, the same way it does for a Planner.

## 8. Out of scope (v1)

- Trailing Limit execution (a limit at an offset from the trigger). Market only.
- ATR or volatility-based distance.
- Rebuilding the best price from candles after the desk was down.
- Trails on spot **Assets**.

## 9. Open questions

| # | Question | My lean |
|---|---|---|
| Q1 | If Lighter accepts an opening Stop Market (phase 0), should a Trail Entry on Mark be venue-held, so it still fires while the desk is down, at a frozen trigger? | No for v1. An entry at a level nobody is following is the wrong way to fail. Maybe later, as an option. |
| Q2 | Exits on Last: is a backstop one step behind the trigger right, given a partial Trail could close up to twice its size if both fire? | Yes, and say it in the confirm. The other option, no backstop, leaves the Position bare while the desk is down. |
| Q3 | With Step up, does the step after a Trail target go to its fill price or its Activation price? | Fill price. It is what the trade actually locked in. |
| Q4 | Can a Planner with a Trail stop have **no** targets (all Runner)? P5 needs one today. | Yes, but only with a Trail stop on. |
| Q5 | Is the per-Market cap of 1 entry, 1 stop and 3 take profits right? | Yes for v1. It keeps the rate budget easy to reason about. |
| Q6 | Should a standalone Trail Entry be able to place a fixed stop when it fills? | No. That is Planner with a Trail entry (TE6). |
| Q7 | Rebuild the best price from 1m candles after a restart? | No. Candles are Last, not mark, and a jump on restart is worse than a missed high. |
| Q8 | ADR 0016: "A Trail is moved or fired by the desk. Exits hold when the desk is down, entries wait"? | Yes. |

## 10. Phases

0. **Venue check** (by hand, minimum size): does a Stop trigger on mark, and does Lighter accept a non-reduce-only Stop Market? These answers settle Q1 and §4.
1. **Rules and ADR 0016**: `trail-rules.md`, CONTEXT.md, and the planner-rules edits written down (not coded yet).
2. **Engine and reference**: `algos/trail/engine.py` with its tests (each kind, both sides, activation, step, gap, floor, rounding), and a trades subscription for each Market that has a Trail on Last.
3. **Trail Stop and Trail Take Profit** on Positions: job, book, COI band, persistence, API, the popover modes, blotter rows, chart lines, Kill warning.
4. **Trail Entry** on the ticket.
5. **Planner**: Trail entry, Trail stop, and Trail targets.

Phases 3, 4 and 5 each depend only on phase 2, so they can be built in parallel once the engine has landed.
