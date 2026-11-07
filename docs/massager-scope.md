# Massager: scope (draft 1)

Scope for an algo that works a Position the operator already holds: it sells some of it as price rises and buys it back as price falls, inside a Band, so the Position earns from the range without leaving the size the operator chose. Not built. When it is, the rules move to `massager-rules.md` and this file is kept for the reasoning.

Words in bold mean what [CONTEXT.md](../CONTEXT.md) says they mean.

## Decided (2026-11-07)

1. It works **both ways**: below its **Core** as price rises, above it as price falls.
2. When price leaves the **Band** it stops trading and holds what it has. It does not return to Core and does not stop the Position out. The **Swing** is the operator's only limit on that risk, so it is a required input.
3. The Core follows outside fills: a Ladder, a Ticket or a hand add moves the Core, not the Massager's **Lean**.
4. It never touches a Stop or Take Profit Ticket.
5. Name: the algo is **Massager**, the size it works around is the **Core**.

## 1. Language (proposed CONTEXT.md entries)

**Massager**:
A desk algo that works an open Position up and down inside a Band, selling above and buying back below, so the Position earns from the range and comes back to its Core. It needs a Position to start. Its orders are Clips. The rules will be in massager-rules.md.
_Avoid_: grid (that's **Grid**), DCA, rebalance, scalper

**Core**:
The size a Massager works around: the Position minus the Massager's Lean. It is set from the Position at start and moves only by outside fills.
_Avoid_: base, main position, target size

**Lean**:
What a Massager holds off its Core: its own Clips' net fills. Above zero the Position is larger than the Core, below zero smaller.
_Avoid_: inventory (that's Grid's), deviation, offset, drift

**Swing**:
The most a Massager's Lean may be, either way. The Position stays between Core − Swing and Core + Swing.
_Avoid_: range (that's the Band), max inventory (that's Grid's)

**Basis**:
What the Position cost after the Massager's realized profit: (entry × size − Captured) ÷ size. Lighter's entry only moves when you add, so a sell high and buy back lower barely moves it. Basis is the number that shows the work.
_Avoid_: entry (that's the venue's), cost (unqualified), breakeven (that's Planner's)

## 2. How it works

### 2.1 Price sets the Lean

The Massager holds no opinion. Each price in the Band has a Lean:

> Lean(price) = −Clip × the number of Steps price is above the **Center**, capped at ±Swing.

At the Center the Position is its Core. Each Step up, it holds one Clip less. Each Step down, one Clip more. At Swing ÷ Clip Steps from the Center it is at its limit and does nothing further that way.

**Example.** LIT, Core 1,000 long, Band 3.20–3.50, Swing 300, Clip 100, Center 3.35. Step = (3.50 − 3.20) ÷ (2 × 300 ÷ 100) = 0.05.

| Price | 3.20 | 3.25 | 3.30 | 3.35 | 3.40 | 3.45 | 3.50 |
|---|---|---|---|---|---|---|---|
| Lean | +300 | +200 | +100 | 0 | −100 | −200 | −300 |
| Position | 1,300 | 1,200 | 1,100 | 1,000 | 900 | 800 | 700 |

Price goes 3.35 → 3.40 → 3.35: it sells 100 at 3.40 and buys 100 back at 3.35. The Position is 1,000 again, Captured is 100 × 0.05 = $5 less fees, and Basis drops by $5 ÷ 1,000. Every round trip is one Clip times one Step.

### 2.2 Orders

A static lattice, not a chase. Each level is a post-only Limit Clip at its price: sells on the levels above the last fill, buys on the levels below. When a buy fills at a level, a sell goes on one Step above it, and the other way round. The touch is not chased, so a tick of noise does not churn the Position.

Only the nearest levels each side rest at once (2 each side in v1), so the lattice does not spend the Market's open-order room or the rate budget. The rest go on as price comes to them.

### 2.3 Inputs

| Input | Required | Note |
|---|---|---|
| Band low, Band high | yes | Price must be inside to start. |
| Swing | yes | Refused if it is not below the Core, so the Position can never go flat or flip from its own trades. |
| Clip | yes | Over the venue minimum, and Swing must divide into whole Clips. |
| Center | no | The price where Lean is 0. Defaults to the Band's middle (open question 1). |

Step is derived: Band width ÷ (2 × Swing ÷ Clip). Starting is refused if a Step does not clear the round-trip maker fees (0 on Standard, but Premium is not) plus one tick.

### 2.4 At start

It reads the Position. Long or short, the Core takes that side; a short Core sells below the Center and buys above it, the mirror image. With no Position it refuses. If price is away from the Center, the Lean at that price is the target, and the first Clips move toward it as post-only orders at the nearest levels, never at market.

### 2.5 The Core moves with outside fills

Core = Position − Lean, always. A Ladder buy of 200 makes the Core 1,200 and the lattice keeps working around it. A hand close of 300 makes it 700.

- Lean is the Massager's own fills, counted from its Clips. It never takes a size from the Position.
- If an outside fill leaves the Core at or below the Swing, so a full sell-side Lean could flatten the Position, the Massager **pauses** with its Clips pulled and says why. Resume needs a smaller Swing or a larger Core.
- If an outside fill takes the Position flat or to the other side, it **stops** and pulls its Clips. What was Lean is gone with the Position.

### 2.6 Outside the Band

Price above the Band: it holds −Swing (or what it got to) and sends nothing. Below: +Swing. Its Clips stay on the edge levels, and it carries on when price comes back in. It never sends a market order to get back to Core.

That is the risk the operator takes on: a break down leaves the Position at Core + Swing with the extra bought on the way down, and a break up leaves it at Core − Swing having sold on the way up. The Swing is the cap on both.

## 3. Beside the rest of the desk

- **One Massager per Market.** It runs beside Chase, Ladder and TWAP, as Grid does ([grid-rules.md](grid-rules.md) G1).
- **Not beside a Planner.** Planner owns the exit and pauses when the Position grows from outside ([planner-rules.md](planner-rules.md) M6), which a Massager does at every Step.
- **Not beside a Trail.** A Trail Take Profit is a share of the Position, and that share would move under it.
- **Not beside a Grid** in v1 (open question 2).
- **Stops are not touched.** A Stop sized to the Core does not cover a positive Lean. A Stop that closes the whole Position covers all of it. The Massager's form says so next to Swing.
- **Auto kill** watches uPnL only and needs nothing new. Kill halts it with the other algos.
- **Position watch** reads the Position as it is. R is measured from the Plan stop, so a larger Position shows a larger risk, which is true.
- **Journal**: the Massager's fills are ordinary fills inside the Position's Round trip. Its Captured is the algo's own count, like Grid's.

## 4. Engine

- A new book and job on `ClipJob`, with Ladder's static rung placement and Grid's own-fill counting. Grid's chase, merge and break-even do not apply.
- Its own client_order_index band, `[13e9, 14e9)`, in lockstep with the web plugins ([ADR 0004](adr/0004-partitioned-client-order-index.md)).
- It persists like Grid: Lean, Captured and the last filled level. On restart Core = Position − Lean, and the lattice goes back on.
- It shares the algo rate budget. A filled level's replacement goes on first, before refilling far levels.

## 5. UI

- **Order ticket → Algo → Massager**, only on a Market with a Position. It shows Core (read-only), Band, Swing, Clip, Center, the derived Step and Captured per round trip, and the Position range Core − Swing to Core + Swing.
- **Working row**: Core, Lean, Position range, Captured, Basis against the venue entry.
- **Chart**: the Band, the Center, and the resting levels.

## 6. Out of scope (v1)

- A Return to Core button. Pausing and a hand order do the same today.
- Moving the Band while it runs. Stop and start again.
- A Massager with no Position.
- Uneven Clips (more size further from the Center).

## 7. Open questions

1. **Center.** The Band's middle, so the Band maps evenly to ±Swing (proposed), or the price at start, so it trades nothing until price moves?
2. **Beside a Grid.** Both keep their own books, so the venue would not mind. Refuse in v1 to keep one range engine per Market, or allow?
3. **Levels resting each side.** 2 is a guess. Fewer is cheaper on the rate budget, more catches a fast move.

## 8. Phases

1. Rules in `massager-rules.md`, the CONTEXT.md entries, and the pure planner (Lean from price, levels, refusals) with its tests.
2. The job on the harness fakes: own-fill counting, the outside-fill rules in 2.5, restart.
3. Desk wiring: book, exclusivity, COI band, persistence, push on error.
4. Ticket form, working row, chart.
