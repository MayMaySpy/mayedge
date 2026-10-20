# The chart drafts a Planner

[ADR 0007](0007-chart-amends-tickets-only.md) says the chart only amends Tickets. A **Draft** is the exception that does not touch the venue: lines for an entry, a stop and targets, with no orders behind them. Nothing is sent until **Start** is pressed in the Planner dialog. Closing that dialog leaves the Draft where it was. Esc clears it.

ADR 0007 still holds for everything live. Dragging a Ticket still amends that Ticket. Clips stay display-only, and a running Planner's stop and targets stay display-only ([ADR 0015](0015-planner-owns-the-exit.md): Planner owns the exit). A Draft is not a Clip and not a Ticket. Dragging it only moves the drawing.

The Draft is per Market and lives in memory. It is one viewer's sketch, not a second way to send an order.
