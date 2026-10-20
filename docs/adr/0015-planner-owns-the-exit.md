# Planner owns the exit on its Market

While a Planner is live on a Market, its stop and targets are the only exit orders there. Attach cancels the Market's Stop and Take Profit Tickets and replaces them with Planner Clips, and the confirm names each one it cancels. Planner Clips allocate from their own client_order_index band, 11e9–12e9 ([ADR 0004](0004-partitioned-client-order-index.md)). The chart does not drag them ([ADR 0007](0007-chart-amends-tickets-only.md)); a change goes through Planner.

Planner resizes the stop with every fill and moves it to Breakeven when the first target fills. A Ticket Stop beside it would close size Planner still thinks is open, and a drag on its own stop would be undone by the next resize. Leaving the operator's Tickets alone would mean two owners of one exit and no single answer to "what is my risk".

A Position whose size changes from outside pauses Planner instead of being reconciled. Guessing whether an outside fill was an add or a partial close would move the stop on a guess.

Amended 2026-10-20: a Position that is only *smaller* from outside is no guess. It was closed by hand, and the stop is tied to the Position, so nothing about the stop moves. Planner now keeps running and resizes its targets to the same shares of what is left ([planner-rules.md](../planner-rules.md) M6). Left at their old sizes, reduce-only targets would close the whole remainder at the first one and leave the rest orphaned. A *larger* Position still pauses: the add changed the entry and the risk at the stop, and only the operator knows whether it belongs to the plan.
