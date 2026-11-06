# Position rules

The **Position watch** tells the operator when something about a Position they hold has changed: it has no stop, it has reached a multiple of its risk, its Idea's stop has closed through, its side is crowded, or funding is eating it. Once a day it sends a brief of every Position. It is built for swing trades: each push says something new, and most go once per Round trip ([ADR 0024](adr/0024-the-desk-watches-what-the-operator-holds.md)).

It reads only what the desk already holds, plus one hourly candle per Position whose Idea has a stop. It never places, amends or cancels an order, never moves an Idea, and never arms Auto kill. Pushes follow [push-rules.md](push-rules.md): the key, the quiet window and the per-minute cap apply.

Knobs are keys in the `push:` block of `backend/config/alerts.yaml`. Words in bold in [CONTEXT.md](../CONTEXT.md) mean the same here. "code" means the number is not a knob yet.

## What it reads

| | Rule | Knob | Pinned by |
|---|---|---|---|
| PW1 | Every 10 seconds the watch reads the account's open Positions and working orders, the algo book, the open Ideas (Watching and Active), the last `journal_open`, and the funding strip (alert-rules F2). Mark is the market's live mark, else the account's. | 10 s is code | `test_a_tick_reads_only_what_it_is_given` |
| PW2 | A Position's **Round trip** is the journal's open Round trip on that Market and side. Until the journal has it, the Round trip is the Market and side. A Position that goes flat forgets its Round trip. | | `test_a_flat_position_forgets_its_round_trip` |
| PW3 | The watch's first look after the desk starts only seeds. An R level, an Idea stop closed through, crowded funding and funding bleed that are already true then are marked seen and not sent. A Round trip that opens later is judged from its first look. No stop and the brief are not seeded. | | `test_what_is_already_true_at_boot_is_not_sent`, `test_a_round_trip_opened_later_is_told` |

## Stops and R

| | Rule | Knob | Pinned by |
|---|---|---|---|
| S1 | A Position is **protected** while a working **Stop** on its Market closes it (a sell for a long, a buy for a short), or while a Planner or Trail is running or paused on its Market. | | `test_a_stop_order_or_a_planner_protects` |
| S2 | Its **stop price** is the trigger of the protecting Stop nearest to mark. A Planner or Trail protects without a stop price. | | `test_the_nearest_stop_is_the_stop_price` |
| S3 | Its **plan stop** is the stop of the open Idea on that Market and side, the most recently updated one if there are several. Without one, it is the first stop price S2 saw in this Round trip, kept while the Round trip lasts, so a stop moved later does not move R. | | `test_the_idea_stop_is_the_plan_stop`, `test_a_moved_stop_does_not_move_r` |
| S4 | **R** is how far mark has moved from entry in the Position's favour, in units of the distance from entry to the plan stop. A loss is negative. No plan stop, or a plan stop at entry, has no R. | | `test_r_is_the_move_over_the_risk` |

## Events

| | Event | When | Text | Key | Urgent |
|---|---|---|---|---|---|
| E1 | No stop | A Position has been unprotected for `no_stop_after_s` (300). One push names every unprotected Position. It is sent again only when a Market joins that set. A Market that is protected again leaves it, and can join again. | `⚠️ No stop on 2 Positions: ETH long 0.5, LIT long 1,000` | `position:nostop:{markets}` | no |
| E2 | Halfway to the stop | R falls to −0.5 or lower. | `ETH long: halfway to the stop, −0.5R (mark 2,212, stop 2,180)` | `position:{trip}:r-0.5` | no |
| E3 | 1R, 2R | R rises to 1 or 2 or higher. Each once. Two levels crossed in one look send only the higher. | `ETH long: +1R (mark 2,297, entry 2,239)` | `position:{trip}:r1`, `:r2` | no |
| E4 | Idea stop closed through | The open Idea on that Market and side has a stop, and the last closed 1h bar closed beyond it: under it for a long, over it for a short. Once per Round trip. | `🔴 ETH long: the 1h bar closed at 2,175, under the Idea's stop 2,180` | `position:{trip}:thesis` | yes |
| E5 | Crowded | The Market is on the funding strip and the Position's side pays: a long with funding above zero, a short below. Once per Round trip per UTC day. | `ETH long: crowded, funding +0.0420%/h is 4.1σ from its day, and longs pay` | `position:{trip}:crowded:{date}` | no |
| E6 | Funding bleed | The Round trip's funding has cost at least `bleed_r` (0.25) of its R in dollars: the distance from entry to the plan stop times size. Once per Round trip. | `ETH long: funding has cost $12, 0.3R of its $40 risk` | `position:{trip}:bleed` | no |
| E7 | Brief | UTC time is at or past `brief_at`, once that UTC date, including a start that missed the minute. One line per Position, by notional. Empty `brief_at` sends nothing; so do no Positions. | `Positions, 07:00 UTC` then `ETH long 0.5 · −$5 · −0.2R · stop 2.1% away · funding −$1` per line. A Position with no stop says `no stop`, one with no R leaves R out, and one whose liquidation price is within 25% says `liq 18% away`. | `position:brief:{date}` | no |

`positions: off` sends none of these. The desk page shows none of them; they are pushes.

## Knobs

| Knob | Default | What it does |
|---|---|---|
| `positions` | `on` | `on` or `off` |
| `no_stop_after_s` | 300 | how long a Position stays unprotected before E1 |
| `bleed_r` | 0.25 | the share of R that funding has to cost before E6 |
| `brief_at` | `07:00` | `HH:MM` UTC for E7. Empty is off. |

The R levels (−0.5, 1, 2), the 1h bar of E4 and the 25% liquidation line of E7 are code.

## Open

1. **A Planner or Trail protects without a price.** (S1, S2) A Position under one has no stop price, so it has R only from its Idea.
2. **R from the first stop seen is forgotten at a restart.** (S3) After a restart the first stop seen is the one resting then, which a Trail may have moved.
3. **E4 reads one timeframe.** A position trade on the 4h is told on the 1h close.
