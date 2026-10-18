# An alert is scored from the price it fired at

Left and Against are read from the 15 one-minute bars after the bar an alert fired in, from the price it fired at. The first clock started at the close of the bar before, which counted the move that raised the alert as what happened after it: Sharp moves showed 81% continued when the five bars after them continued 42% of the time (73 alerts, 11 Oct 2026).

The score is two distances, not a hit rate. A row that said "continued" or "failed" had to pick a horizon and a sign for every kind of alert, and most kinds had no claim to test. How far the price went each way says whether there was anything left to do, and leaves the verdict to the operator. Which rows the operator opens is recorded beside it.

`alert_outcomes` holds rows scored on the old clock. Nothing reads it.
