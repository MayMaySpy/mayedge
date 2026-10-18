# A Trail is moved by the desk, and holds when the desk is down

Lighter has no trailing order. Its Stop and Take Profit triggers fire on mark, at a fixed price. So a **Trail** is a desk algo: for an exit on Mark it keeps a real reduce-only Stop Market on the venue and Amends its trigger as the best price moves; for an entry, and for an exit on Last, the desk watches the price and sends its own Market order, with a venue Stop one step behind as a backstop for the exit. Rules are in [trail-rules.md](../trail-rules.md).

The trigger only moves toward profit. When the desk is down nothing moves it, so an exit's stop holds at the last price it was given and still fires there. An entry, or an exit not yet activated, does not fire at all. Each of these fails safe: an exit is never looser than the desk left it, and nothing opens on a level nobody is watching. The UI says "follows only while the desk is running", so a Trail is never mistaken for a venue trailing stop.

An opening (non-reduce-only) Stop on the venue would let a trailing entry fire while the desk is down, at a frozen trigger. The SDK sends one, but Lighter's docs do not say it opens a Position, and an entry at a level nobody is following is the wrong way to fail. Entries stay desk-held.

Every move is an Amend, one transaction in the 40-a-minute bucket. A Trail moves only by a step of at least 10% of its distance, at most every 5s, and the Trails on one Market share 15 Amends a minute. A fire is never held back.
