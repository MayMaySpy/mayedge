# Push rules

A **Push** is a Telegram message the desk sends the operator. It repeats a fact that already happened. It raises nothing, and it never places, amends, or cancels an order.

The `push:` block in [`backend/config/alerts.yaml`](../backend/config/alerts.yaml) is the source of truth for the knobs. Both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` must be set, or every call is a no-op and the rest of the desk is unchanged. There is no inbound command. `/kill` from Telegram would be the first way to trade that does not go through the desk page; it needs its own decision and an ADR.

Pushes are outbound only. The desk posts `sendMessage`. It does not open a webhook and it does not poll `getUpdates`. The desk has no public ingress ([ADR 0005](adr/0005-no-app-auth-loopback-tailscale.md)); do not Funnel.

A push never blocks or fails a trading path. `push()` returns immediately and does not raise. A worker sends later. A failure in that worker is a dropped message, not a failed order.

## Events

The first algo snapshot after boot only seeds the diff. A restart does not replay fills that were already on the book.

| Event | When | Text | Key | Urgent |
|---|---|---|---|---|
| Near liquidation | an alert row whose rule is `near_liq`, on every `alerts` mode except `off` | `🔴 ETH near liquidation — mark 2,412.5, liq 2,301 (4.6%)` | `alert:{id}` | yes |
| Held-market alert | `alerts` is `held` or `all`, and the row names a Held market. A price spike uses the move fact; anything else uses the row note. | `ETH spike: price 3.1× the hour's biggest minute, +0.8% · held` | `alert:{id}` | no |
| Other alert | `alerts: all` sends the note. `alerts: urgent` sends a row at severity 3 or above. `alerts: held` sends neither. `off` sends nothing. | the row's note | `alert:{id}` | no |
| Auto kill fired | `fired_at` changes after the boot seed | `⛔ Auto kill fired: uPnL −$812 crossed the −$800 floor. Stopping algos, cancelling, flattening.` A profit cross names the target instead of the floor. | `autokill:{fired_at}` | yes |
| Auto kill flattened | the kill status is `killed` and the latest account snapshot has no open Position | `Auto kill: flattened, 0 Positions open` | `autokill:{fired_at}:result` | yes |
| Auto kill could not flatten | the kill status is `partial` | `⚠️ Auto kill could not flatten after 3 tries — 1 Position open: ETH −2.0` | `autokill:{fired_at}:result` | yes |
| Algo error | an algo's status moves to `error`. Sent for every family, on both `errors` and `lifecycle`. | `Planner ETH stopped with an error: book rejected` | `algo:{id}:error` | no |
| Planner entry | `algos: lifecycle`, and the entry fill count rose | `Planner ETH long: entry filled 1.5 @ 2,430 · stop 2,390 · risk $60` | `algo:{id}:entry` | no |
| Planner stop | the stop fill count rose | `Planner ETH: stop filled @ 2,300` | `algo:{id}:stop` | no |
| Planner target | a `tpN` fill count rose | `Planner ETH: target 1 filled @ 2,510 (+2.0R)` | `algo:{id}:target-{n}` | no |
| Planner done | status moves to `done` | `Planner ETH long: done` | `algo:{id}:done` | no |
| Trail entry, stop, target | `algos: lifecycle`, and `filled` rose. The kind is `entry`, `stop`, or `tp`. | `Trail ETH short: entry filled 1.5 @ 2,412.5` | `algo:{id}:entry` (or `:stop`, `:target`) | no |
| Trail done | status moves to `done` | `Trail ETH short: done` | `algo:{id}:done` | no |
| Venue down | `venue_down_since` has been set for `venue_down_after_s` | `Lighter down since 14:02 UTC (503)` — UTC, and the reason when there is one | `venue` | no |
| Venue back | the venue is up again after a down push. This one is not dropped by the down message's quiet window. | `Lighter back after 6m` | `venue` | no |
| Account feed stale | `account_ws` is not `live` for `account_stale_after_s`, and a Position is open or an algo is `running` or `paused`. Once per outage; going live clears it. | `⚠️ Account feed stale 2m with 2 algos live — desk is blind` | `account_stale` | yes |
| Desk started | after `desk.restore()` | `Desk up (mainnet) — 3 algos restored, 2 Positions open` | `boot` | no |
| Backup failed | a Backup raises. The loop keeps running and tries again at the next `backup_at`. | `⚠️ Backup failed: disk full` | `backup` | no |
| Yesterday's journal | UTC time is at or past `daily_at`, once that UTC date, including a start that missed the minute. The numbers are the UTC journal day 24 hours earlier, the same day key the journal uses. Closed Round trips only; partial and open stay out. Empty `daily_at` sends nothing. A failed read is logged and that local date is not tried again. **Portfolio part** (docs/portfolio-rules.md D1): when the desk has the venue's daily buckets stamped at both UTC midnights of that day, the line leads with the Portfolio's change that day and each kind that moved. Without both buckets, or if that read fails, the line goes out without it. | `Yesterday: Portfolio +$412 (Perps +$380, Spot +$40, Staking −$8) · Net +$380 over 9 Round trips, fees $38, funding −$6`. Without the Portfolio part: `Yesterday: Net +$412 over 9 Round trips, fees $38, funding −$6`. None closed: `Yesterday: no Round trips.` (or `… · no Round trips.` after the Portfolio part) | `journal:{local date}` | no |
| Send test | the Alerts panel, or `POST /api/push/test` | `Desk test push ✓` | `test:{time}` | yes |

`algos: errors` still sends the error row. It does not send entry, stop, target, or done. Chase, Grid, Ladder, and TWAP send an error and nothing else.

The could-not line counts one try per flatten slippage step. There are three steps.

Sizes use a unicode minus (`−2.0`). A loss in dollars does too (`−$812`). Prices use thousands separators and drop trailing zeros.

## Debounce

| Knob | Default | What it does |
|---|---|---|
| `alerts` | `held` | `held`, `urgent`, `all`, or `off` |
| `algos` | `lifecycle` | `errors` or `lifecycle` |
| `venue_down_after_s` | 60 | how long the venue stays down before the down push |
| `account_stale_after_s` | 120 | how long the account feed stays quiet before the stale push |
| `repeat_s` | 600 | the same key stays quiet this long. Urgent skips it. The venue-back push skips it too. |
| `max_per_min` | 12 | past this many sends in a minute, non-urgent items wait and leave as one `N more: a; b` when the minute ends. Urgent still goes. |
| `daily_at` | empty | `HH:MM` UTC for yesterday's journal. Empty is off. |

The worker also sends at most one message a second. An HTTP 429 waits `parameters.retry_after` and tries again; it is not one of the three failures. After eight 429s in a row it counts as a failure. Any other error waits 2s, then 4s, then 8s, then the message is dropped and one warning is logged. The warning does not include the exception or the request.

## The message itself

Dynamic text is HTML-escaped (`&`, `<`, `>`). The result is cut at 4,000 characters. When the desk's network is testnet, the message starts with `[testnet] `.

The bot token lives only in the send URL. It is not logged, not returned by `GET /api/push`, and not shown in the panel. httpx request logging stays at WARNING, because that log line would contain the token.
