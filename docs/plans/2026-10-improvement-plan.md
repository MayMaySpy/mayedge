# Improvement plan — October 2026

Eight pieces of work: five features, three pieces of upkeep. Each section says what to build, where it goes, how to test it, and when it is done. The sections are written so separate agents can take them, and the order section says which can run side by side.

| # | Work | Kind | Size |
|---|---|---|---|
| A | Telegram pushes | Feature | M |
| B | Trade journal | Feature | L |
| C | Alert record over 30 days, with a what-if | Feature | M |
| D | Hotkeys | Feature | S–M |
| E | Draft a Planner on the chart | Feature | L |
| F | CI noise and bundle size | Upkeep | S |
| G | Split the biggest files | Upkeep | M |
| H | Restart test across every algo | Upkeep | M |

---

## 0. Ground rules (read before any section)

1. **Read first:** [README.md](../../README.md), [CONTEXT.md](../../CONTEXT.md), the rules doc for the area you touch (`docs/*-rules.md`), and the ADRs in [docs/adr](../adr). Words in bold mean what CONTEXT.md says. A new word goes into CONTEXT.md in the same commit that introduces it, with an `_Avoid_:` line.
2. **Rules before code** ([ADR 0011](../adr/0011-alert-rules-are-written-down-before-they-are-coded.md)). Behaviour lands in one commit: the rule in the doc, the code, and the test that pins it.
3. **Commit straight to `main`.** No branches, no PRs. Keep commits small. Write the message as one plain sentence ending in a period, like `git log` shows (e.g. "Add a Ladder entry to Planner."). End every message with the `Co-Authored-By` line. Do not push unless the user asks.
4. **`make ci` is green before every commit:** ruff, basedpyright and unittest for the backend; oxlint, vitest and build for the web.
5. **The local desk is live mainnet in Docker** (`:14200`). Never place, amend or cancel an order on it to test something. Read live data through the desk's own API, never by calling Lighter directly. Test order flow with the fakes in `backend/tests/chase_harness.py` and `backend/tests/planner_harness.py`.
6. **One viewer.** The desk serves one tab and one operator. Do not build sync between viewers or locking.
7. **Auto kill only watches uPnL.** That is deliberate. Nothing here adds a realized-PnL or equity limit to it, and the journal (B) must not suggest one.
8. **Secrets** live in `backend/.env` only: never in the web bundle, never in logs, never in an API response.
9. **Match the code around you:** Python dataclasses with Protocol stores (see `alert_log.py`), `from __future__ import annotations`, `logger = logging.getLogger(__name__)`, a single `threading.Lock` around SQLite (`db._lock`), React function components with hooks, and `@/` imports.

---

## A. Telegram pushes

### Goal
When no tab is open, the desk still acts on its own — algos, Auto kill, the flatten retries — but nobody hears about it. Send the events that matter to the operator's Telegram. A push is a toast that leaves the desk ([ADR 0013](../adr/0013-an-alert-is-a-fact-and-a-toast-is-a-coincidence.md)). It is not a new kind of Alert, and it does not decide anything.

### Docs first
- `docs/push-rules.md`: every event that pushes, its text, its debounce, and its knob. The `push:` block in `alerts.yaml` is the source of truth.
- `docs/adr/0017-a-push-is-a-toast-that-leaves-the-desk.md`. It records: outbound only in v1; long polling, never a webhook (the desk has no public ingress — [ADR 0005](../adr/0005-no-app-auth-loopback-tailscale.md), do not Funnel); a push never blocks or fails a trading path.
- CONTEXT.md: add **Push** — "A Telegram message the desk sends the operator. It repeats a fact; it raises nothing new." `_Avoid_: notification, alert (for the message itself)`.
- README: a "Pushes" subsection under Alerts, plus the setup steps below. `.env.example`: the two new variables, commented.

### Settings
`backend/src/mayedge/config.py` → `Settings`:
```python
telegram_bot_token: str | None = None
telegram_chat_id: str | None = None

@property
def push_enabled(self) -> bool:
    return bool(self.telegram_bot_token and self.telegram_chat_id)
```
Add a `push:` block to `backend/config/alerts.yaml`, parsed next to the other blocks in `thresholds_from_dict` (or in its own loader, if that reads cleaner):
```yaml
push:
  # Which alert rows push: held (Held markets and Near liquidation), urgent, or all. off to mute.
  alerts: held
  # Algo pushes: errors (an algo stops with an error) or lifecycle (also Planner/Trail entry, stop, target).
  algos: lifecycle
  # Venue down pushes only after this many seconds; recovery pushes with how long it lasted.
  venue_down_after_s: 60
  # The account feed counts as stale after this long while a Position or algo is live.
  account_stale_after_s: 120
  # The same push key stays quiet for this long.
  repeat_s: 600
  # Above this many pushes in a minute, the rest are folded into one digest.
  max_per_min: 12
```

### Module `backend/src/mayedge/push.py`
- `class TelegramPusher` with a `Transport` Protocol, so tests inject an `httpx.MockTransport`. The real transport is an `httpx.AsyncClient` (already a dependency) posting to `https://api.telegram.org/bot{token}/sendMessage` with `chat_id`, `text`, `parse_mode="HTML"` and `disable_web_page_preview=True`.
- `push(key: str, text: str, *, urgent: bool = False) -> None` is **synchronous and never raises**. It drops the item on an `asyncio.Queue` and returns. One worker task drains the queue.
- Pace: at most 1 message a second, the per-chat limit Telegram documents. On HTTP 429, sleep for `parameters.retry_after` and retry. On other errors, back off 2s, 4s, 8s, then drop the message and log one warning. An item marked urgent (Auto kill, Near liquidation) goes to the front of the queue.
- Dedupe: the same `key` within `repeat_s` is dropped. Urgent items ignore this.
- Digest: past `max_per_min`, the non-urgent items are held and sent as one "N more: …" message at the end of the minute.
- HTML-escape `& < >` in every dynamic value. Truncate at 4,000 characters (Telegram's limit is 4,096).
- **The token must never be logged.** httpx logs request URLs at INFO, and the URL contains the token. Set `logging.getLogger("httpx").setLevel(logging.WARNING)` in this module, and never log the URL or the exception's request. A test proves that no log record contains the token.
- If `push_enabled` is False, every call is a no-op. Nothing else in the desk changes.
- Prefix every message with the network when it is testnet (`[testnet]`), so a test desk is never mistaken for the real one.

### What pushes, and where to hook it
Hook in at **one place where possible**: `lifespan` in `backend/src/mayedge/api/app.py` already routes desk, feed-health and Auto kill messages through `fanout.push`. Add one `pusher.on_desk_msg(msg)` subscriber there that switches on `msg["type"]`. First check that every source below reaches that stream: `grep -n "AlertDetector(" -r backend/src` shows where alerts get their `broadcast`, and it may not be `fanout`. Where a source does not reach it, call `pusher` directly at that source rather than rerouting the source.

| Event | Source | Text (example) | Key / urgent |
|---|---|---|---|
| Held-market Alert, Near liquidation | `AlertDetector._emit` events (`held != ""`, or rule `near_liq`) | `🔴 ETH near liquidation — mark 2,412.5, liq 2,301 (4.6%)` · `ETH spike: price 3.1× the hour's biggest minute, +0.8% · held` | `alert:{id}` · urgent for `near_liq` |
| Other alerts | same, filtered by `push.alerts` | the row's `note` / `describe()` text | `alert:{id}` |
| Auto kill fired | `AutoKill._fire` start (reason, uPnL) | `⛔ Auto kill fired: uPnL −$812 crossed the −$800 floor. Stopping algos, cancelling, flattening.` | `autokill:{fired_at}` · urgent |
| Auto kill result | `AutoKill._record(status=…)` | `Auto kill: flattened, 0 Positions open` · or `⚠️ Auto kill could not flatten after 4 tries — 1 Position open: ETH −2.0` | urgent |
| Algo error | diff of `type: "algo"` snapshots per `algo_id`: status moves to `error` | `Planner ETH stopped with an error: <error>` | `algo:{id}:error` |
| Planner / Trail lifecycle (`algos: lifecycle`) | the same diff: entry filled, stop filled, target filled, done | `Planner ETH long: entry filled 1.5 @ 2,430 · stop 2,390 · risk $60` · `Planner ETH: target 1 filled @ 2,510 (+2.0R)` | `algo:{id}:{event}` |
| Venue down / back | `feed_health` (`venue_down_since`), debounced by `venue_down_after_s` | `Lighter down since 14:02 (503)` · `Lighter back after 6m` | `venue` |
| Account feed stale while exposed | `feed_health` `account_ws != live` for `account_stale_after_s` while a Position or algo is live | `⚠️ Account feed stale 2m with 2 algos live — desk is blind` | `account_stale` · urgent |
| Desk started | end of `lifespan` startup, after `desk.restore()` | `Desk up (mainnet) — 3 algos restored, 2 Positions open` | `boot` |

For the algo diff, keep `last_status: dict[str, str]` and the last fill counts per algo. Read the snapshot fields in each book's `snapshot()`/`to_dict()` (Planner: `algos/planner/job.py::snapshot`). The first snapshot after boot only seeds the diff; it never pushes, so a restart does not replay old events.

### API
- `GET /api/push` → `{enabled, chat_set, alerts, algos}` (never the token or chat id).
- `POST /api/push/test` → sends `Desk test push ✓` and returns `{ok, error?}`.
- Web: in the Alerts panel's menu, a "Pushes: on/off · Send test" line. Show it only when enabled.

### Tests (`backend/tests/test_push.py`)
`httpx.MockTransport` plus a fake clock. Cover: pacing at 1/s; 429 honours `retry_after`; three failures drop the message and the caller never sees an exception; dedupe within `repeat_s`; urgent skips dedupe and jumps the queue; digest past `max_per_min`; HTML escaping and truncation; the token never appears in any log record (use `assertLogs` at DEBUG on the root logger); disabled means no transport calls; each event row in the table above produces its text (feed it the real message shapes); the first algo snapshot after boot pushes nothing.

### Setup steps for the operator (put these in the README)
1. In Telegram, message `@BotFather` → `/newbot` → copy the token.
2. Send your new bot any message, then open `https://api.telegram.org/bot<token>/getUpdates` and copy `message.chat.id`.
3. Put `TELEGRAM_BOT_TOKEN=` and `TELEGRAM_CHAT_ID=` in `backend/.env`, then `make push-env && make deploy`.
4. Use **Send test** in the Alerts panel.

### Out of scope (v1)
Inbound commands. A read-only `/status` (Positions, uPnL, live algos) via `getUpdates` long polling, gated to `chat_id`, is a fine v2 and needs its own section in the ADR. **`/kill` from Telegram needs an explicit decision by the user and an ADR** — it would be the first way to trade that does not go through the desk page.

### Done when
All rows in the event table push on a real bot (check with testnet, or by feeding the real message shapes in a script against the desk — never by triggering Auto kill on mainnet). `make ci` is green, and the docs, ADR, CONTEXT and README are updated.

---

## B. Trade journal

### Goal
History lists raw fills from the venue. Rebuild those fills into **Round trips** — flat to flat in one Market — and show what the desk actually made: net of fees and funding, by day, Market and algo. Planner trades are also scored in **R**, because Planner knows its stop.

### Docs first
- `docs/journal-rules.md`: how fills become Round trips (flips, partial closes, history that starts mid-Position), how fees and funding are charged to a Round trip, how an algo is assigned, and how R is computed.
- CONTEXT.md:
  - **Round trip**: "A Position in one Market from flat to flat. A flip ends one Round trip and starts the next at the same fill." `_Avoid_: trade (a Lighter trade is one fill), position (that is the live thing)`
  - **R**: "A Round trip's net result divided by the risk at its stop when it opened. Only Planner Round trips have one." `_Avoid_: RR, risk-reward (for the result)`
  - **Net**: "Realized PnL less fees, plus funding received (or less funding paid)."

### Data
The venue trade rows (`lighter/parse.py::desk_account_trade`) already carry `trade_id, market_index, symbol, side, is_maker, price, size, usd_amount, fee, pnl, type, timestamp`. Funding comes from `account_service.fetch_account_funding`.

New tables. Bump `SCHEMA_VERSION` in `db.py` and add the steps to `_migrate`, following the pattern already there:
```sql
CREATE TABLE IF NOT EXISTS journal_fills (
    trade_id TEXT PRIMARY KEY,
    market_index INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,             -- buy | sell, from the account's side
    is_maker INTEGER NOT NULL,
    price TEXT NOT NULL,
    size TEXT NOT NULL,
    usd TEXT NOT NULL,
    fee TEXT NOT NULL,
    pnl TEXT NOT NULL,              -- the venue's realized PnL on this fill
    kind TEXT NOT NULL,             -- the venue's type: trade | liquidation | ...
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_fills_ts ON journal_fills(market_index, ts);

CREATE TABLE IF NOT EXISTS journal_funding (
    market_index INTEGER NOT NULL, ts INTEGER NOT NULL, amount TEXT NOT NULL,
    PRIMARY KEY (market_index, ts)
);

CREATE TABLE IF NOT EXISTS journal_notes (
    trip_key TEXT PRIMARY KEY,      -- "{market_index}:{first trade_id}"
    note TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    updated_at INTEGER NOT NULL
);
```
Only fills, funding and notes are stored. **Round trips are rebuilt on read** — a few thousand fills a year is cheap, and it means a rule change never needs a data migration.

### Sync — `backend/src/mayedge/journal_sync.py`
- Page through `fetch_account_trades` (newest first, 100 a page, `next_cursor`) and stop at the first page that contains a `trade_id` already stored. Funding the same way.
- Every call goes through the shared REST budget (`budget.take()` is already inside the fetch). Read [docs/lighter-limits.md](../lighter-limits.md) and stay inside it. A sync is low priority: use at most one page per budget slot, and yield to orders.
- When: 30s after boot; every 5 minutes; and a debounced resync 10s after the account feed reports a fill (reuse the account message the desk already handles).
- The first backfill runs back as far as the venue keeps data. Record the oldest timestamp reached in `meta` as `journal_oldest_ts`.
- Writes are idempotent (`INSERT OR IGNORE`).
- Do nothing when `settings.trading_enabled` is False.

### Rebuilding — `backend/src/mayedge/journal.py` (pure functions, no I/O)
- `round_trips(fills, funding, algo_links, planner_risk) -> list[RoundTrip]`, per Market, in timestamp order:
  - Keep a signed running Position. A fill that crosses zero is **split** at zero: one part closes the old Round trip, the rest opens the new one, and the fee is shared in proportion to size.
  - Realized PnL is the sum of the venue's `pnl` on closing fills. Do not recompute it — the venue's number is the truth. Keep a recomputed value (from average entry and exit) only as a check in tests.
  - Funding in a Round trip is the funding rows in the Market with `open_ts <= ts <= close_ts`.
  - A Round trip whose first fill is older than `journal_oldest_ts`, or that starts with a closing fill, gets `partial=True` and is excluded from the headline stats (but listed).
  - A Round trip that is still open is shown as `open=True`, with its uPnL taken from the live Position, and is excluded from realized stats.
- Algo: map `trade_id` → `algo_id` via `algo_trade_ids` / `algo_fills` (already in `db.py`). The family is the `algo_id` prefix or the book. The Round trip's algo is the one with the most opening size; `manual` if none.
- R: for a Planner Round trip, risk = |entry − stop| × size, using the plan stored in `algo_runs` for that `algo_id` (check what Planner persists in `planner/state.py` and the run row; if the initial stop is not stored, **store it** when the plan starts, and mark older Planner Round trips "R n/a"). R = Net / risk.
- `summary(trips, group_by: day|market|algo|none)` → per group: count, wins, losses, win %, gross PnL, fees, funding, Net, average win, average loss, profit factor, expectancy (Net per Round trip), largest win and loss, maker share of volume, and average and total R where present. Group `none` also returns the realized Net curve (cumulative, per close) and its maximum drawdown in dollars.

### API (`backend/src/mayedge/api`, or the journal router if G has landed)
- `GET /api/journal/trips?since=&until=&market=&algo=&limit=` → trips, each with its fills.
- `GET /api/journal/summary?range=7d|30d|90d|all&group=day|market|algo|none`
- `PUT /api/journal/trips/{trip_key}/note` with body `{note, tags}`.
- `POST /api/journal/sync` → starts a sync now; returns `{started, last_synced_at}`.

### Web
- New Positions tab **Journal**, next to History: `web/src/components/widgets/account/JournalTab.tsx`. Load it lazily (see F).
- Summary strip: Net, Fees, Funding, Win %, Profit factor, Expectancy, Avg R (Planner only), Max drawdown. Range picker 7d / 30d / 90d / All; Market and algo filters.
- One chart: daily Net as a histogram, with the cumulative Net line on the same time axis, using `lightweight-charts` (already a dependency). Follow the desk's colors and the 12px type scale.
- Table of Round trips: Market, side, opened, held for, size, avg in → avg out, Net, R, algo, note. A row expands to its fills. Notes are edited in place. `partial` rows are dimmed and say why.
- Add the client calls to `web/src/lib/api.ts`, in the same style as the ones around them.

### Tests
- `backend/tests/test_journal.py` (pure): open → close; scale in, partial close, close; a flip split at zero with the fee shared; history starting mid-Position (`partial`); an open Round trip; funding inside and outside the window; algo choice by most opening size; R with and without a stored stop; summary maths (profit factor with no losses = `None`, not infinity); drawdown on a known curve.
- `backend/tests/test_journal_sync.py`: paging stops at a known `trade_id`; replays are idempotent; nothing runs without trading enabled; budget is taken per page (fake budget).
- Web: `JournalTab` renders the summary and a row from fixture data, and expanding a row shows its fills.

### Done when
The Journal tab on the local desk shows the real account's history (read-only sync through the desk). The summary's Net for a chosen day matches the venue's realized PnL less fees for that day, checked by hand against History. CI is green and the docs are in.

---

## C. Alert record over 30 days, with a what-if

### Goal
The desk already scores every alert row with **Left**, **Against** and **Opened** (`alert_rows` table, `alert_log.py`), but the panel only shows 24 hours. Show the record over 7, 30 and 90 days, break it down, and let the operator test a tighter knob against what actually happened, so `alerts.yaml` is tuned from evidence ([ADR 0012](../adr/0012-an-alert-is-scored-from-the-price-it-fired-at.md)).

### Docs first
`docs/alert-rules.md` gets a "Record" section: what each column means, and that the what-if can only **tighten** a knob. A looser knob would have raised rows that were never written, so the desk cannot replay them — say that in the UI too.

### Retention
`alert_rows` is purged at `outcomes.retention_days` (30). Add a separate knob `rows.log_retention_days: 90`, used by `AlertLog` (`alert_log.py:211`) for `alert_rows` only, and leave the `alert_outcomes` retention alone.

### Backend
- Extend `AlertLog.stats(since_ms)` → `stats(since_ms, *, by: rule|rule_severity|rule_direction|held|hour|symbol)`. Per group: n, measured, median Left, median Against, p25/p75 of each, **share where Left > Against**, Opened count and rate. Keep the current output shape as the `by=rule` default so the panel's 24h record does not change.
- `whatif(rule, knob, value, since_ms)`: keep only rows whose headline fact would still clear `value`. Map each knob to the fact field it is judged on by reading the `_*_fact` functions in `alerts.py` and `describe()`. For example, `spike.price_x` → the `price` fact's `value` (the multiple); `liquidations.min_usd` → the liq fact's `size`; `held.liq_distance_pct` → the near_liq fact's distance. Return the stats for the kept rows next to the baseline. Only knobs in that explicit map are offered; an unknown knob is a 400.
- Endpoints: `GET /api/alerts/stats?hours=&by=` (extend the existing one) and `GET /api/alerts/whatif?rule=&knob=&value=&days=`.

### Web
- A **Record** dialog opened from the Alerts panel, next to the 24h record line. Range 7d / 30d / 90d; a group-by picker; a table sorted by n. Show "too few rows" when n < 20, and do not color those rows.
- What-if row: pick a rule, then a knob (only the ones mapped for that rule); the current value is prefilled from `GET /api/alerts` settings or a new `GET /api/alerts/settings`. A number input shows baseline vs. what-if side by side: n, median Left, median Against, Left > Against share. A line under it: "Only tighter values can be tested."
- It is read-only: the dialog never writes `alerts.yaml`. It shows the yaml line to change.

### Tests
`backend/tests/test_alert_stats.py` / `test_alert_log.py`: grouping, percentiles, share computation, retention split; what-if on a fixed row set for each mapped knob; a looser value returns the baseline unchanged with a flag `looser=True`; an unknown knob raises. Web: the dialog renders the fixture and the what-if updates on input.

### Done when
With the real container DB, the dialog shows 30 days per rule, and a what-if on `spike.price_x` returns fewer rows with their stats.

---

## D. Hotkeys

### Goal
Fast keyboard control of the things done many times a day, without making it easy to trade by accident.

### Design
- One keymap in `web/src/lib/hotkeys.ts` (the single source, also used by the help sheet) and one `useHotkeys` hook in `web/src/hooks/useHotkeys.ts`, mounted once in `Dashboard.tsx`.
- Ignored while focus is in an `input`, `textarea`, `select` or `[contenteditable]`, or while any dialog or popover is open. Keys are matched by `e.code` where the layout matters.
- **Trading keys need Shift and are off until armed.** "Hotkey trading" is a toggle in the Order panel, stored in `localStorage` (a per-viewer convenience; wrap reads in try/catch), and off by default. While armed, the Order panel shows a small persistent badge. Every trading hotkey shows a toast saying what was sent.

| Key | Action | Notes |
|---|---|---|
| `Shift+B` / `Shift+S` | Market buy / sell at **Quick size** | Same handler as the floating Buy/Sell (`QuickTradePanel.tsx`); armed only |
| `Shift+X` | Cancel this Market's Tickets | Same as the Orders tab's Bids + Asks (`cancel-side`, both sides); armed only; never Cancel all, so Clips — a Planner's stop among them — stay with the algo |
| `Shift+K` | **Open** the Kill dialog | Never fires Kill directly |
| `1`–`7` | Pinned timeframe 1–7 | `TimeframePins.tsx` order |
| `/` or `Mod+K` | Open the Market picker | `MarketPicker.tsx` |
| `F` | Toggle the current Market in Favorites | |
| `C` / `S` / `W` | Chart / Scan / Watch mode | |
| `A` | Arm or disarm Axis rest | |
| `P` | Open Planner for this Market (Attach if a Position is open) | Reuse the ticket's open logic |
| `Esc` | Existing: cancel a drag or edit | Keep the `ChartWidget.tsx` handler working; move it to the hook if that is clean |
| `?` | Show the hotkey sheet | A dialog built from the keymap |

### Tests
`web/src/lib/__tests__/hotkeys.test.ts` and a hook test: dispatch; the focus guard (inputs, dialogs); trading keys do nothing while disarmed and call the handler once while armed; key repeat (`e.repeat`) never sends a second order; `Shift+K` opens and does not kill.

### Done when
Every key in the table works on the local desk, with trading keys checked against the harness or with the order call mocked — **not** by sending orders to mainnet. The sheet lists every key. CI is green.

---

## E. Draft a Planner on the chart

### Goal
Place a Planner's entry, stop and targets by clicking and dragging on the price chart, then open the Planner dialog filled in. This is the largest change to how the chart is used, so it starts with an ADR.

### Decision first
[ADR 0007](../adr/0007-chart-amends-tickets-only.md) says the chart only amends Tickets. Write `docs/adr/0018-the-chart-drafts-a-planner.md`: the chart may draw a **Draft** — lines with no orders behind them — and nothing reaches the venue until **Start** is pressed in the Planner dialog. ADR 0007 still holds for everything live. A running Planner's lines stay display-only ([ADR 0015](../adr/0015-planner-owns-the-exit.md): Planner owns the exit). Add **Draft** to CONTEXT.md. Update `docs/planner-rules.md` with a "Drafting on the chart" section.

### Design
- A "Plan" toggle in the chart toolbar, next to Axis. While it is on: first click = entry, second click = stop (the side follows from entry vs. stop), and targets are placed at the dialog's default R multiples. Esc clears the Draft.
- Each line is draggable, reusing the drag code in `web/src/lib/chartTradingLines.ts` and the chart's pointer handling. Labels show price, distance in %, R for targets, and size from the current sizing mode via the existing `POST /api/algos/planner/preview`, debounced at 250ms.
- Venue minimums: use the preview's warnings (see the latest commit, "Check each Ladder rung against the venue minimum at its own price.") and show them on the Draft.
- "Open in Planner" (and Enter) opens `PlannerDialog.tsx` with the Draft's values as initial form state. Edits in the dialog do not move the Draft back; closing the dialog keeps the Draft until Esc.
- If a Position is open on the Market, a Draft opens Planner as **Attach** (stop and targets only, no entry), matching the ticket's behaviour.
- The Draft is per Market and lives in memory only.

### Tests
Chart line logic as pure functions (click order → side; drag → price snapped to tick; R labels); `PlannerDialog` accepts the initial values; the preview is debounced. Keep pixel and canvas work out of the unit tests.

### Done when
A Draft becomes a Planner preview identical to entering the same numbers by hand, with no request to start anything until Start. The ADR, CONTEXT and planner rules are in.

---

## F. CI noise and bundle size

1. **Lint warnings**
   - `web/src/components/widgets/AutoKillSection.tsx:30`: setState inside an effect. Derive the value during render, or set it in the event that changes it.
   - `web/src/components/widgets/ChartWidget.tsx:847`: a ref read during render. Move the read into an effect or handler, or keep the value in state.
2. **`ResourceWarning: unclosed database`** in the backend tests. Find it with `PYTHONTRACEMALLOC=10 uv run python -W error::ResourceWarning -m unittest discover -s tests`, then close the connection in that test's `tearDown` (or call `db.close_db()`).
3. **vitest `localStorage is not available` warnings** (Node's experimental global). Silence them in config, not per test — e.g. pass `--localstorage-file` through vitest's pool `execArgv`, or make the jsdom `localStorage` the one used. Tests must not depend on the real global.
4. **Bundle:** one 952 KB file today.
   - `React.lazy` + `Suspense` for `ScanBoard`, `WatchBoard`, `PlannerDialog`, the trail dialog, `TradeHistoryTab`, `FundingHistoryTab` and the new `JournalTab`. Fallbacks match each panel's empty state.
   - `build.rollupOptions.output.manualChunks` (in Vite 8, check whether the option is now `rolldownOptions`): `react`, `lightweight-charts`, UI primitives.
   - Check whether `radix-ui` is still imported anywhere now that the desk is on Base UI. Remove it if unused. `shadcn` is a CLI and should not be a runtime dependency — move it to `devDependencies` or drop it.
   - Target: the first chunk is under 500 KB with no chunk-size warning. Report the before/after sizes in the commit message.
5. **Done when:** `make ci` prints no warnings from our code.

---

## G. Split the biggest files

These are pure moves: **no behaviour change**, one commit per file, and the tests already there pass unchanged (do not edit them except for imports).

1. **`backend/src/mayedge/api/app.py`** (48 routes) → `api/routes/` with one `APIRouter` per area: `alerts.py`, `scan.py`, `markets.py`, `account.py`, `orders.py`, `algos.py`, `kill.py`. `create_app` keeps the middleware, exception handlers and `lifespan`, and includes the routers. Shared helpers (`_trade`, `_account_history`, `_require_trading`, `_market_index`) go to `api/deps.py`. `tests/test_api_contract.py` and `test_browser_guard.py` must pass untouched.
2. **`web/src/components/widgets/ChartWidget.tsx`** (1,823 lines) → a `widgets/chart/` folder:
   - `chartPrefs.ts`: the `load*` functions and their storage keys (lines ~227–310).
   - `Readouts.tsx`: `OhlcReadout`, `OhlcField`, `LiqsReadout`, `NumeraireReadout`.
   - `useChartTicketInteraction.ts`: the pointer, Amend, Axis and Esc effect (~849–1178).
   - `useChartSeries.ts`: the series sync effects.
   - `ChartWidget.tsx` keeps composition only. Target: under 600 lines.
3. **`backend/src/mayedge/algos/planner/job.py`** (1,609 lines) → split by phase, keeping `PlannerRunner` and its public methods where they are:
   - `entry.py`: `_evaluate_entry`, `_work_chase`, `_rest_entry`, `_amend_chase`, `_work_ladder`, `_pending_rungs`, `_track_entry`, `_fire_entry`.
   - `manage.py`: `_evaluate_manage`, steps (`_due_step`, `_take_step`, `_step_price`), trailing (`_trail_stop`, `_trail_targets`, `_trail_target`), `_fire_target`.
   - Use module functions that take the runner, or small helper classes the runner owns — pick whichever keeps basedpyright happy without `Any`. `tests/test_planner_job.py`, `test_planner_trail.py` and `test_planner_book.py` stay untouched.
4. Optional if there is budget: `alerts.py` (1,020 lines; split the detector from the row book), `web/src/lib/liveData.ts` (1,200 lines).

**Done when:** each file is under its target and `make ci` is green after every commit.

---

## H. Restart test across every algo

### Goal
Each algo persists in SQLite and is restored at boot (`desk.restore()` → each book's `restore()`). Prove, for all six — Chase, Grid, Ladder, TWAP, Planner and Trail — that a restart in the middle of a run neither doubles nor loses anything.

### Design
- A shared fake venue for tests. Start from `tests/chase_harness.py` and `tests/planner_harness.py`, and pull what they share into `tests/venue_harness.py` without breaking the tests that use them.
- One test module, `tests/test_restart.py`, parameterised by algo type. For each one:
  1. Point `settings.db_path` at a temp file and call `init_db()`.
  2. Start the algo on the fake venue and advance it to a mid-run state (resting Clips, a partial fill, and for Planner and Trail a working stop).
  3. Call `drain_for_shutdown()`, close the DB, and throw the book away.
  4. While the "desk is down", change the venue: fill one Clip, cancel another from outside.
  5. Build a fresh book on the same DB and call `restore()`, then let the account snapshot arrive.
  6. Assert: no duplicate venue orders; `client_order_index` continues inside the family's band ([ADR 0004](../adr/0004-partitioned-client-order-index.md)); a live Clip is adopted, not re-sent; the downtime fill is counted once, with evidence ([ADR 0003](../adr/0003-invent-fill-needs-evidence.md)); remaining size is right; Planner's stop and Trail's trigger are still where they were left ([ADR 0016](../adr/0016-a-trail-is-moved-by-the-desk.md)).
- Any failure found is a real bug. Fix it in its own commit with the rule doc updated, and list it in the final report.

### Done when
All six algos pass. Bugs found are fixed or written up for the user with a failing test marked `expectedFailure` and a reason.

---

## Order and parallel work

Several sections touch the same files. Run work side by side only when the files below do not overlap.

| Section | Owns (writes) |
|---|---|
| A | `push.py`, `config.py`, `alerts.yaml` (`push:`), `api/app.py` lifespan plus 2 routes, AlertsPanel menu, `docs/push-rules.md`, ADR 0017 |
| B | `journal*.py`, `db.py` migration, journal routes, `account/JournalTab.tsx`, `PositionsPanel.tsx` (tab), `api.ts` (journal calls) |
| C | `alert_log.py`, `alerts.py` (retention knob only), alert routes, `AlertsPanel.tsx` + Record dialog, `alert-rules.md` |
| D | `hotkeys.ts`, `useHotkeys.ts`, `Dashboard.tsx` (mount), `QuickTradePanel.tsx`, `OrderTicket.tsx` (arm toggle) |
| E | `chartTradingLines.ts`, chart folder, `PlannerDialog.tsx`, ADR 0018 |
| F | `AutoKillSection.tsx`, one line of `ChartWidget.tsx`, `vite.config.ts`, vitest config, `package.json`, lazy imports in `Dashboard.tsx` / `PositionsPanel.tsx` |
| G | `api/app.py` → `api/routes/*`, `ChartWidget.tsx` → `chart/*`, `planner/job.py` → `planner/*` |
| H | `tests/*` only (plus any bug fixes, which may touch algo code) |

**Recommended order**

1. **Wave 1, side by side:** A (Telegram — closes the largest safety gap), F, H. A and F both touch `AlertsPanel`/`Dashboard` only lightly; land F first if they collide.
2. **Wave 2, alone:** G. It moves the files the later waves add to, so doing it before them is cheaper than merging around it. Rebase A's routes into `api/routes/` here if A landed first.
3. **Wave 3, side by side:** B, C, D. Their files do not overlap after G. B and C both add routes — each goes in its own router file.
4. **Wave 4:** E, after the user has read and agreed to ADR 0018.
5. **Afterwards (small):** once B is in, add an optional daily push from A: "Yesterday: Net +$412 over 9 Round trips, fees $38, funding −$6". Knob `push.daily_at: "08:00"`, off by default.

Because every agent commits to `main`, an agent running in parallel must `git pull --rebase` before committing, touch only the files its section owns, and re-run `make ci` after the rebase.

---

## Decisions the user still owes (defaults in place, so work can start)

| Decision | Default in this plan |
|---|---|
| Which alerts push | `held` (Held markets and Near liquidation), plus Auto kill, algo errors, venue down, account feed stale |
| Planner/Trail lifecycle pushes | On (`algos: lifecycle`) |
| Inbound Telegram commands | None in v1; `/status` read-only is a v2; `/kill` only with an explicit yes and an ADR |
| Alert row retention | 90 days |
| Hotkey trading | Off until armed in the Order panel; trading keys need Shift |
| Chart Draft (E) | Waits for the user to agree to ADR 0018 |
