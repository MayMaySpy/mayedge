# Push rules

A **Push** is a Telegram message the desk sends the operator. It repeats a fact that already happened. It raises nothing, and it never places, amends, or cancels an order.

The `push:` block in [`backend/config/alerts.yaml`](../backend/config/alerts.yaml) is the source of truth for the knobs. Both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` must be set, or every call is a no-op and the rest of the desk is unchanged. The one inbound command is a read-only `/status` (Commands, below). `/kill` from Telegram would be the first way to trade that does not go through the desk page; it needs its own decision and an ADR.

Pushes are outbound. The desk posts `sendMessage`, and for Commands it long-polls `getUpdates`, which is also a request the desk makes. It never opens a webhook. The desk has no public ingress ([ADR 0005](adr/0005-no-app-auth-loopback-tailscale.md), [ADR 0017](adr/0017-a-push-is-a-toast-that-leaves-the-desk.md)); do not Funnel.

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
| Desk started | after `desk.restore()`. A gap shorter than `down_after_s` keeps the plain line. A longer one is urgent and names the Down gap, whether the stop was clean, and that Trails, Planner trailing parts and Auto kill were not watching. Venue stops held. | `Desk up (mainnet) — 3 algos restored, 2 Positions open`. After a long gap: `Desk up (mainnet) after 2h 14m down (02:10–04:24 UTC, not a clean stop). Trails, Planner trailing parts and Auto kill were not watching; venue stops held. 3 algos restored, 2 Positions open.` "not a clean stop" becomes "clean stop" when it was one. | `boot` | only with a gap |
| Desk frozen | the wall clock jumped more than 30s while the loop missed its ticks, without a restart. Urgent, key `freeze:{to}`. Positions and uPnL come from the cached account payload. If the account feed is not live, the line says they are unknown and does not wait. | `Desk was frozen 14m (02:10–02:24 UTC). Trails, Planner trailing parts and Auto kill were not watching; venue stops held. 2 Positions open, uPnL −$120.` | `freeze:{to}` | yes |
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
| `down_after_s` | 60 | a boot after this many seconds names the Down gap. A shorter gap stays the plain restart line. |
| `repeat_s` | 600 | the same key stays quiet this long. Urgent skips it. The venue-back push skips it too. |
| `max_per_min` | 12 | past this many sends in a minute, non-urgent items wait and leave as one `N more: a; b` when the minute ends. Urgent still goes. |
| `daily_at` | empty | `HH:MM` UTC for yesterday's journal. Empty is off. |

The worker also sends at most one message a second. An HTTP 429 waits `parameters.retry_after` and tries again; it is not one of the three failures. After eight 429s in a row it counts as a failure. Any other error waits 2s, then 4s, then 8s, then the message is dropped and one warning is logged. The warning does not include the exception or the request.

## The message itself

Dynamic text is HTML-escaped (`&`, `<`, `>`). The result is cut at 4,000 characters. When the desk's network is testnet, the message starts with `[testnet] `.

The bot token lives only in the send URL. It is not logged, not returned by `GET /api/push`, and not shown in the panel. httpx request logging stays at WARNING, because that log line would contain the token.

## Commands

`commands: status` (the default) answers `/status`; `commands: off` reads nothing. The bot answers only while pushes are on.

- The desk long-polls `getUpdates` for messages, 50 seconds a request. It reads only messages whose chat is `TELEGRAM_CHAT_ID`; every other chat is ignored without a reply.
- `/status` (also `/status@yourbot`) answers through the push queue, under the key `status:{update_id}`. It says what the desk holds and watches now, from the same messages the desk page gets: Positions with their uPnL, total uPnL, live algos, Auto kill with its floor and target, whether the account feed is live, and whether Lighter is down.

  `Desk status (mainnet), 14:00 UTC` · `2 Positions open, uPnL +$123: ETH +1.5 (+$100), BTC −0.1 (+$23)` · `No algos live` · `Auto kill armed: floor −$500, target +$1,000`, one per line. Without a live account feed it adds `Account feed not live: Positions as last seen`.
- Any other command gets `Only /status is answered here. The desk takes no orders from Telegram.` Plain text gets nothing.
- A command older than 120 seconds is not answered: it was sent while the desk was down, and an answer now would read as an answer then.
- Nothing a command does places, amends or cancels an order, arms or disarms Auto kill, or changes a knob.
- A second reader of the same bot (a second desk with the same token, or a webhook) makes Telegram refuse `getUpdates` with 409. The desk logs the failure once, without the URL, which holds the token, and tries again after 5, 15, then every 60 seconds.

Pinned by `tests/test_push_inbox.py`.
