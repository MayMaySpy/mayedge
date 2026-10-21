# Reliability plan — late October 2026

Eight pieces of work, run by **one agent, end to end, in the order below**. There is no new trading feature here. The desk works; this plan makes it keep working: one Python everywhere, a database that survives a lost volume, an event loop that never stalls behind a read, an SDK that knows today's market indexes, and a desk that says when it was not watching.

The account stays on Lighter **Standard** (0 fees). Every section is written for Standard's limits: 60 requests and 40 transactions a rolling minute. Nothing here asks for a tier change.

| # | Work | Kind | Size |
|---|---|---|---|
| A | One Python everywhere | Upkeep | S |
| B | CI warnings | Upkeep | S |
| C | Desk database Backups | Feature | M |
| D | Keep the event loop free | Fix | M |
| E | Lighter SDK 1.1.8 and the venue refresh | Fix | M |
| ⏸ 1 | Rebuild the desk, verify, operator checks | Checkpoint | — |
| F | Send budget readout | Feature | S |
| G | Know when the desk was not watching | Feature | M |
| ⏸ 2 | Rebuild the desk, verify | Checkpoint | — |
| H | Batch probe on testnet (optional) | Probe | S |

What the review found, measured on the live desk on 2026-10-21:

| Finding | Evidence |
|---|---|
| The desk runs Python 3.12; dev and CI test on 3.14 | `docker exec … python --version` → 3.12.15; `uv run python --version` → 3.14.0 |
| SQLite reads run on the event loop inside `async def` routes | `/api/journal/summary` 160 ms, `/api/journal/trips` 100 ms, `/api/oi/BTC` 125 ms; each blocks every algo step, book update and Auto kill check for that long |
| The hourly OI fold scans 8.2M rows twice under `db._lock`, on the loop | `(minute_index * 60) / 3600 < ?` cannot use `idx_oi_samples_minute`: `SCAN … COVERING INDEX`, 306 ms per scan, two scans an hour, even when nothing is old enough to fold |
| The desk database has no Backup | `mayedge.db` is 632 MB in the `mayedge-data` volume and nowhere else (8.2M OI samples, 327k Funding prints, the alert record, the journal) |
| `lighter-sdk` is six releases behind | Locked at 1.1.2; 1.1.8 is out. 1.1.4: "fix cancel all market index range issue". 1.1.7: market indexes widened from int16 to int64, binary options added. Live market indexes now reach **4510** (`weETH/USDC`), perps reach 4099 (`DRV`) |
| Every non-spot market type is read as a perp | `normalize_market_type` in `lighter/models.py` returns `perp` for anything that is not spot. Lighter now lists binary option markets |
| Nobody hears when the desk stops | When the desk process, its container or its host stops (a crash, a deploy, a reboot, a paused VM), Trails, Planner trailing parts, Auto kill and Pushes all stop, and a Push cannot report its own desk's death. True in local Docker now and on the VPS later |
| The send budget is invisible | `lighter/budget.py` keeps the window, but nothing shows how much of it is used or why an algo is waiting |

Already in place, so not in this plan: Position-row Stop + Take Profit already go out as one OCO group (`create_sl_tp` in `lighter/orders.py`). The funding prune is already indexed. `funding_days` is empty on purpose: `backfill_funding_days` skips when the venue's day does not calibrate.

---

## 0. Ground rules (read before any section)

1. **Read first:** [README.md](../../README.md), [CONTEXT.md](../../CONTEXT.md), the rules doc for the area you touch (`docs/*-rules.md`), and the ADRs in [docs/adr](../adr). Words in bold mean what CONTEXT.md says. A new word goes into CONTEXT.md in the same commit that introduces it, with an `_Avoid_:` line.
2. **Rules before code** ([ADR 0011](../adr/0011-alert-rules-are-written-down-before-they-are-coded.md)). Behaviour lands in one commit: the rule in the doc, the code, and the test that pins it.
3. **Commit straight to `main`.** No branches, no PRs. Keep commits small: at least one per section, more where a section says so. Write the message as one plain sentence ending in a period, like `git log` shows. End every message with the `Co-Authored-By` line. Do not push unless the user asks.
4. **Stage only your own files.** Run `git status` before you start. If it shows changes you did not make, they are the user's work in progress: never stage, stash, reset or reformat them. Use `git add <path>`, never `git add -A` or `git add .`.
5. **`make ci` is green before every commit:** ruff, basedpyright and unittest for the backend; oxlint, vitest and build for the web.
6. **The local desk is live mainnet in Docker** (`:14200`). Never place, amend or cancel an order on it. Read live data through the desk's own API (`curl http://127.0.0.1:14200/api/...`) or through a **read-only** SQLite connection inside the container (`sqlite3.connect('file:/app/data/mayedge.db?mode=ro', uri=True)`). Never call Lighter directly from your shell with the account's keys.
7. **Never start a second backend with `backend/.env`.** It would be a second desk on the same account: it would restore the same algos and send for them twice. Run the backend only through tests, or through the scripts this plan names, which never start the gateway, the order service or the desk.
8. **Rebuild the live desk only at a checkpoint (⏸), and only after the user says yes in chat.** `make up` restarts the container, and with it every live algo. It is not silent on the venue: shutdown pulls Chase and Ladder-entry Clips (planner-rules E15, EL5), and restore puts them back. Ask with a plain line: what changed, which algos are live now (from `/api/algos`), and that those Clips will come off and go back on.
9. **One viewer.** **Auto kill only watches uPnL.** **Standard tier stays.** Nothing here changes those.
10. **Secrets** live in `backend/.env` only: never in the web bundle, never in logs, never in an API response. That now includes `HEARTBEAT_URL` (G): the URL is the secret.
11. **Match the code around you:** Python dataclasses with Protocol stores (see `alert_log.py`), `from __future__ import annotations`, `logger = logging.getLogger(__name__)`, the single `threading.Lock` around the writer connection (`db._lock`), React function components with hooks, and `@/` imports.
12. **Measure, then claim.** Every section that is about time states the number before and after, measured the way the section says, in its commit message and in the final report.

---

## A. One Python everywhere

### Goal
The desk that trades runs Python 3.12 (`Dockerfile`: `FROM python:3.12-slim`). Dev runs 3.14, and CI runs whatever `setup-uv` picks. So the interpreter that trades is the one nobody tests. Make all three the same: **3.12**, because that is what has run the live desk for weeks.

### Steps
1. Add `backend/.python-version` containing `3.12`. `uv` and `astral-sh/setup-uv` both read it.
2. `backend/pyproject.toml`: `requires-python = ">=3.12"`, basedpyright `pythonVersion = "3.12"`, ruff `target-version = "py312"`.
3. Recreate the venv: `cd backend && rm -rf .venv && uv sync --group dev`. Confirm `uv run python --version` prints 3.12.x.
4. `make ci-backend`. If anything fails, it is code that only works on 3.13+. Fix it in place (no `sys.version_info` branches). List each one in the commit message.
5. `.github/workflows/ci.yml` needs no change if `uv sync` picks up `.python-version`. Check by reading the setup-uv action's docs for the pinned version (`astral-sh/setup-uv@v10.0.1`). If it does not, add `python-version: "3.12"` to that step.

### Done when
`uv run python --version`, the CI job and `docker exec mayedge-mayedge-1 python --version` all print 3.12. `make ci` is green.

---

## B. CI warnings

1. `web/src/components/widgets/AlertRecordDialog.tsx:95`, `react(set-state-in-effect)`. The effect seeds `rule`, `knob` and `value` from the first entry of `settings.by_rule` once settings arrive. Do it without an effect: either derive the first rule and knob during render while `rule` is unset, or seed them in the `.then` of the fetch that loads `settings`. The Record dialog's tests must pass unchanged. If none of them covers "opens on the first rule's first knob", add that test first.
2. Backend tests print `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`. Read the warning's full text and the installed Starlette's changelog. If the fix is a dev dependency the warning names, add it to the `dev` group. If that would mean replacing the test client across the suite, filter exactly this one warning in the unittest entry point instead, with a comment linking the Starlette issue.
3. **Done when:** `make ci` prints no warnings from our code or from our test setup.

---

## C. Desk database Backups

### Goal
The desk's history exists in one place: the `mayedge-data` Docker volume. A `docker compose down -v`, a lost or reset volume, or a corrupt file loses all of it, including the alert record that took months to gather. Keep a daily **Backup** on the host's own disk, outside Docker, and prove it restores. The host is local Docker during alpha and the VPS after. The code and the compose file must not care which: a relative bind mount next to `docker-compose.yml`, nothing machine-specific.

### Docs first
- CONTEXT.md: **Backup**: "A compressed copy of the desk database taken while the desk runs, kept on the host outside Docker." `_Avoid_: snapshot, dump, export`.
- README: a "Backups" subsection under Data covering where Backups land, how many are kept, `make backup`, and the restore steps below, word for word.

### Settings
`backend/src/mayedge/config.py` → `Settings`:
```python
backup_dir: str = ""        # empty: Backups off
backup_keep: int = 7        # newest daily Backups kept
backup_at: str = "03:30"    # UTC, HH:MM
```
`docker-compose.yml`: add a bind mount `./backups:/app/backups` and `BACKUP_DIR: /app/backups` under `environment`. Add `backups/` to `.gitignore`.

### Module `backend/src/mayedge/backup.py`
- `def take_backup(db_path: Path, dest_dir: Path, *, now: datetime) -> Path` is synchronous. It always runs in a worker thread (`asyncio.to_thread`), never on the loop.
  1. Open its **own** read-only connection: `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)`. Never use `db._connect()` and never take `db._lock`. In WAL mode a reader does not block the writer.
  2. `VACUUM INTO '<dest_dir>/.mayedge-<stamp>.db.tmp'`. This is a consistent copy, and compact.
  3. `PRAGMA quick_check` on the copy. If it is not `ok`, delete the copy and raise.
  4. gzip it to `mayedge-YYYY-MM-DD.db.gz.tmp`, `fsync`, rename to `mayedge-YYYY-MM-DD.db.gz`, then remove the uncompressed temp. The rename is the commit point, so a crash never leaves a file that looks finished.
  5. Prune: keep the newest `backup_keep` files matching `mayedge-*.db.gz`. Never touch any other file in the folder.
- `class BackupLoop` owns one task, started in `lifespan` (`api/app.py`) after `desk.restore()`. It waits 10 minutes after boot, takes a Backup if today's file is missing, then sleeps until the next `backup_at`. Use the injectable `Clock` pattern from `push.py`, so tests do not sleep.
- On failure: log one `logger.exception`, then `pusher.push("backup", "⚠️ Backup failed: <reason>")` (not urgent). Never raise into the loop.
- State for health: `last_backup_at` (ms), `last_backup_bytes`, `last_backup_error`. Add them to `GET /api/health` under a `backup` key. When `backup_dir` is empty, `backup` is `null`.
- CLI: `python -m mayedge.backup` takes one Backup now with the same settings and prints the path. `Makefile`: `backup:` → `docker compose exec mayedge python -m mayedge.backup`.

### Restore (README, and test it once by hand on a copy, never on the live volume)
```bash
docker compose down            # never -v
gunzip -k backups/mayedge-2026-10-21.db.gz
docker run --rm -v mayedge_mayedge-data:/data -v "$PWD/backups":/b alpine \
  sh -c 'cp /b/mayedge-2026-10-21.db /data/mayedge.db && rm -f /data/mayedge.db-wal /data/mayedge.db-shm'
docker compose up -d
```
Check the real volume name with `docker volume ls` before writing it into the README. Compose prefixes it with the project name.

### Tests (`backend/tests/test_backup.py`)
Work on a temp DB built with `init_db()` and a few rows in several tables:
- A Backup opens and has the same row count in every table as the source.
- The file name is the UTC date. A second Backup on the same day replaces the first.
- Pruning keeps `backup_keep` files and leaves unrelated files alone.
- A failed `quick_check` (monkeypatch it) leaves no file behind and records `last_backup_error`.
- `take_backup` never acquires `db._lock`: hold `db._lock` in the test while the Backup runs, and it still finishes.
- The loop schedules on the fake clock: it fires 10 minutes after boot when today's file is missing, skips when it exists, and fires next at `backup_at` UTC.
- A failure calls the pusher once and the loop keeps running.
- With `backup_dir` empty, nothing starts and `/api/health` shows `"backup": null`.

### Done when
`make ci` is green. Once rebuilt at ⏸ 1, `backups/` on the host holds today's file, `/api/health` shows it, and the README's restore steps were run once against a scratch volume.

---

## D. Keep the event loop free

### Goal
The desk runs on one asyncio loop: the market and account feeds, the order book, every algo's step, Auto kill's check, and the HTTP routes. A route that reads SQLite synchronously stops all of them. Today that is 100–160 ms on each Journal or OI request, and twice an hour about 300 ms each for the OI fold. Afterwards no request and no retention job stalls the loop for more than **20 ms**, and the desk can say how far its loop is lagging.

### Docs first
- CONTEXT.md: **Loop lag**: "How late the desk's event loop ran a timer it set, in ms. Above 250 ms the desk is late on everything at once." `_Avoid_: latency, lag (unqualified)`.
- No ADR. This is a fix, not a decision.

### D1. Measure first
1. Take a Backup with C's CLI (`make backup` needs the rebuild, so before ⏸ 1 run the same `VACUUM INTO` from a read-only connection inside the container). Copy the result out with `docker cp` into your scratch folder. You now have a real 632 MB database to profile. Never profile against the live file.
2. Write `backend/scripts/profile_reads.py`. It sets `settings.db_path` to that copy, refuses if the path resolves to anything inside the Docker volume, and **never starts the gateway, the order service, the account service or the desk**: it only imports the read functions. It calls the read functions behind each heavy route (`_trips()` and `summary()` for the journal, `store.list_open_interest`, `store.list_funding`, `store.funding_averages`, `store.summarize_liquidations`, `portfolio_buckets`), and the OI fold, under `cProfile`. It prints wall time per call, best of 5.
3. Record those numbers. They are the "before" for the commit messages.

### D2. Loop lag monitor — `backend/src/mayedge/loop_watch.py`
- One task, started first thing in `lifespan`. It sleeps 250 ms on `loop.time()` and records how late it woke: `lag_ms = (actual − expected) × 1000`.
- Keep a 60-second ring. `snapshot()` → `{"loop_lag_ms": last, "loop_lag_max_60s_ms": max}`, merged into `GET /api/health` next to `feed_health.snapshot()`.
- A single lag over 250 ms logs one WARNING, at most once a minute, with the lag.
- `MAYEDGE_ASYNCIO_DEBUG=1` (an env var, off by default) turns on `loop.set_debug(True)` and `loop.slow_callback_duration = 0.05`. asyncio then logs the callback that blocked. Use it while working on D3–D5. Document it in `backend/README.md`.
- G reuses this task to detect a Freeze, so give it a `wall` clock alongside the monotonic one now: an injectable `Clock` with `mono()` and `now()`, the same shape as `push.py`'s.

### D3. A reader connection — `backend/src/mayedge/db.py`
- Add a second connection used only for reads: `_reader` with its own `_read_lock`, opened with `file:{path}?mode=ro` and `uri=True`, `check_same_thread=False`, `row_factory = sqlite3.Row`. Open it lazily after `_connect()` has created and migrated the file. Close it in `close_db()`.
- `@contextmanager def reading() -> Iterator[sqlite3.Connection]` takes `_read_lock` and yields `_reader`.
- Move every **read-only** store function that a route calls onto `reading()`: the `list_*`, `summarize_*`, `funding_averages`, `portfolio_buckets` and `journal_load_*` family (they live in `db.py` and the `persist_*.py` modules `db.py` re-exports). A function that writes stays on `_lock` and `_connect()`.
- In WAL mode readers do not block the writer, and the writer does not block readers. So a long Journal read in a thread can no longer hold `_lock` while the loop waits to insert an OI sample.

### D4. Routes off the loop — `backend/src/mayedge/api/routes/`
- Keep every handler `async def`. Inside, gather what lives in loop memory first, then run the DB and build work with `await asyncio.to_thread(...)`. Example: `_upnl()` reads `account_service._summary`, so it stays on the loop. Do not turn handlers into plain `def`: FastAPI would then run the loop-memory reads in a thread too.
- Routes to move: `journal.py` (`get_trips`, `get_summary`, and the note PUT's write), `markets.py` (`/api/liquidations`, `/api/liquidations/summary` including its `fold_liquidations_if_due()`, `/api/oi/{symbol}`, `/api/funding/{symbol}`, `/api/funding/{symbol}/average`), `portfolio.py` (`/api/portfolio/history`, `/api/portfolio/days`), and any other route D1 shows above 5 ms.
- **Journal cache.** `_trips()` rebuilds every Round trip from every fill on every request. Add a module-level generation counter in `persist_journal.py`, bumped by every function there that writes. In `api/routes/journal.py`, cache the parsed inputs (fills, funding, links, Planner risk, oldest ts) keyed on that generation. Only `build_trips(..., upnl=...)` runs per request, in the thread, with the uPnL read on the loop. If D1 shows `build_trips` itself dominates, also cache the closed trips per generation and rebuild only the open ones. Decide from the profile, and say which in the commit.

### D5. The OI fold uses its index — `backend/src/mayedge/persist_oi.py`
- `_fold_locked` filters `WHERE (minute_index * ?) / ? < ?`. SQLite cannot use `idx_oi_samples_minute` for an expression, so it scans all 8.2M rows twice an hour. For non-negative integers, `(m * 60) / 3600 < H` is the same as `m < H * 60`. Rewrite both the `foldable` CTE and the `DELETE` as `minute_index < ?` with `fold_before_hour * (OI_HOUR_S // OI_MINUTE_S)`. Keep the hour bucketing in the `SELECT` as it is.
- `fold_open_interest_if_due()` runs inside `flush_open_interest`, on the loop. Move the fold to `asyncio.to_thread` from `gateway._oi_sample_loop` (the call site in `lighter/gateway.py`), still holding `_lock` while it writes.
- Fold in chunks: process at most one day of hours per transaction, commit, release `_lock`, and repeat until nothing is left. The first real fold on the live DB comes due on 2026-10-22, when the oldest samples pass 30 days. It must not hold the writer for seconds.
- Check the plan with `EXPLAIN QUERY PLAN` in a test: it must say `SEARCH … (minute_index<?)`, not `SCAN`.

### Tests
- `tests/test_loop_watch.py`: with a fake clock, lag is late-wake time; the 60s max rolls off; the WARNING is rate-limited.
- `tests/test_loop_free.py`: a helper `assert_loop_free(coro, max_gap_ms=50)` runs a 10 ms ticker beside the coroutine and fails if any tick is late by more than the gap. For each moved route, patch its loader to `time.sleep(0.3)` and assert the loop stays free. Run the same test against the old code once, to see it fail, before you move the route.
- `tests/test_persist.py` (or `test_open_interest.py`): fold equivalence. Build samples on both sides of an hour boundary and of the 30-day line, fold with the old SQL (kept in the test as a literal) and with the new, and compare `oi_hours` and the remaining `oi_samples`. Add the `EXPLAIN QUERY PLAN` check. Chunked folding over three days of hours gives the same result as one pass.
- Journal cache: a write bumps the generation and the next request sees it; two requests with no write parse the fills once (count calls on a patched `journal_load_fills`); uPnL is read fresh every request.
- `tests/test_api_contract.py` passes untouched. Response shapes do not change.

### Done when
D1's script, re-run, shows each heavy read's time unchanged or better. The loop-free test passes for every moved route. After ⏸ 1, `loop_lag_max_60s_ms` on the live desk stays under 20 ms while you open the Journal page, the OI pane and the Portfolio page (read it from `/api/health` with `curl` in a loop). The before and after numbers are in the commit messages.

---

## E. Lighter SDK 1.1.8 and the venue refresh

### Goal
The desk signs with `lighter-sdk` 1.1.2. Since then Lighter has added market indexes past 4,000, binary option markets, and a signer fix for Cancel all's market index range (1.1.4). Kill relies on Cancel all. Bring the SDK current, prove the desk passes every market index through unchanged, keep markets the desk does not understand out of it, and bring the venue limits doc up to date for Standard.

### E1. Read the diff before the upgrade
1. Copy the installed `lighter/signer_client.py`, `lighter/ws_client.py`, and the `lighter/models/` file names to your scratch folder.
2. `cd backend && uv add "lighter-sdk>=1.1.8,<1.2"`. This updates `pyproject.toml` and `uv.lock`.
3. Diff the signer and the ws client. For every SDK call the desk makes (`grep -rn "self.signer\.\|signer\.\|lighter\.[A-Z][a-zA-Z]*Api" backend/src`), check that its signature, return shape, defaults and constants (`NIL_MARKET_INDEX`, `CANCEL_ALL_TIF_*`, `ORDER_TYPE_*`, `ORDER_TIME_IN_FORCE_*`, `GROUPING_TYPE_*`, `DEFAULT_*_EXPIRY`) are the same. Write the result as a table in the commit message: call, changed?, what the desk does about it.
4. Known changes to look at closely:
   - `modify_order` gained `order_version` (default `NIL_ORDER_VERSION`). The desk keeps the default: one viewer, so there is no concurrent Amend to guard.
   - Market indexes are int64 in the signer. Find every place the desk narrows a market index (`int16`, `& 0xFFFF`, `< 256`, `<= 255`, or a `NIL_MARKET_INDEX` comparison). There should be none outside the SDK. Prove it with `grep`.
   - Binary option models. See E2.
   - 1.1.8 "fixed authorization headers for PnL and historical trades". `portfolio_venue.py` and `journal_sync.py` read those. Check they still authenticate the way they do today.
5. `make ci`. Fix what breaks: in the desk's code, never by pinning around it.

### E2. Markets the desk does not understand stay out
- `lighter/models.py`: `normalize_market_type(raw) -> Literal["perp", "spot", "other"]`. Missing or empty stays `perp`, as today: current perp rows may omit the field. Check the raw values in the 1.1.8 models and in one live `orderBookDetails` row read through the desk. Anything with "spot" is spot. A known perp value is perp. Anything else, including binary options, is `other`.
- `lighter/gateway.py::_load_markets`: skip `other` rows the same way it skips inactive ones, and log one INFO line per boot listing the skipped symbols and their raw types. If 1.1.8's `order_book_details` response grows a third list (for binary options), do not read it.
- Positions and orders on a market the desk skipped: `account.py` must not crash on them. Check where `merge_positions` (`lighter/parse.py`) and the order flattening look up market meta. A missing meta must never raise. Do **not** change what Auto kill counts or what Kill flattens: Auto kill's uPnL is deliberate (ground rule 9). Kill already reports a leg it cannot send as a failed leg. If you think either should change, write it up for the user instead.
- Tests (`test_market_type.py` or the nearest existing file): raw `None`, `"perp"`, `"spot"`, the 1.1.8 binary option value, and an unknown string map as above. `_load_markets` with a binary row leaves it out of `/api/markets`, Scan, alerts and the Funding backfill. An account snapshot with a Position on an unknown market index publishes without raising.

### E3. Every market index passes through
- `tests/test_cancel_tickets.py` (it already mocks `signer.cancel_all_orders`): `cancel_all_orders(None)` sends `signer.NIL_MARKET_INDEX`; `cancel_all_orders(4099)` sends `4099`; `cancel_all_orders(4510)` sends `4510`.
- `create_market_order`, `create_limit_order`, `create_sl_tp` and `cancel_order` on market 4099 reach the signer with `market_index=4099`. Use the existing fakes.
- Kill (`kill.py`) with Positions on markets 1 and 4099 sends one Cancel all and a flatten for each.

### E4. The limits doc — `docs/lighter-limits.md`
Re-read [rate limits](https://apidocs.lighter.xyz/docs/rate-limits) and [trading](https://apidocs.lighter.xyz/docs/trading), then update the doc and its "Last reviewed" date:
- **Mayedge stays on Standard** (0 fees). The budget in `lighter/budget.py` is designed for it, and nothing in the desk assumes Premium.
- Standard: 60 requests a rolling minute, unweighted. But when a premium-weighted endpoint allows fewer than 60, the lower number applies (`changeAccountTier` → 8/min). List the weights of the endpoints the desk calls, and the per-minute cap each implies on Standard (weight 600 `recentTrades` → 40/min, for example). `grep` the desk for each one.
- Transaction type limits: default 40/min, `L2UpdateLeverage` 40/min. They apply in addition to the 60.
- Grouped orders count as one transaction ("count as one transaction for quota"). The desk already sends Stop + Take Profit that way.
- `sendTxBatch`: up to 50 transactions in one request, consecutive nonces, same API key; about 15 is safe over REST. The docs do not say whether a batch is one or N against the 40/min type limit. H measures it. Until then the desk does not batch.
- `code: 200` means accepted, not filled. The desk already confirms from the account feed.
- The binary option markets, and that the desk skips them (E2).

### E5. Before ⏸ 1
Write `docs/plans/2026-10-sdk-operator-check.md`: the operator's own steps, in order, with what each one proves. The agent never does these.
1. Place one post-only limit far from the touch, at Quick size, on a perp with index ≥ 4095 (e.g. `STONK`, `DRV`). It rests. Proves create on a high index.
2. Amend its size from the Orders tab. Proves modify.
3. **Cancel all** on that Market from the Orders tab. It is gone. Proves per-market Cancel all on a high index, the 1.1.4 fix.
4. With no algo live, rest one far post-only limit on BTC and one on `STONK`, then **Kill** without flatten. Both are gone. Proves all-markets Cancel all with indexes on both sides of 255.
5. Read `/api/health`. `trading_enabled` is true and both feeds are live.

### Done when
`uv.lock` pins 1.1.8 (or newer 1.1.x). The diff table is in the commit message. E2 and E3 tests pass. The limits doc is current. The operator check file exists. `make ci` is green.

---

## ⏸ 1. Rebuild, verify, operator checks

1. Read `/api/algos`, then ask the user in chat: "A, B, C, D and E are committed. Rebuilding restarts the desk. Live algos: <list, or none>. Chase and Ladder-entry Clips come off at shutdown and go back on at restore; venue stops stay on. OK to run `make up`?" Wait for a yes.
2. `make up`, then read only:
   - `/api/health`: `status ok`, `market_ws` and `account_ws` `live`, `loop_lag_max_60s_ms` present, `backup` present.
   - `/api/markets`: the count matches before the rebuild, minus any `other` markets the boot log names.
   - `/api/algos`: the same working algos as before the rebuild.
   - `docker exec mayedge-mayedge-1 python --version` → 3.12.
   - `docker compose logs --since 15m`: no tracebacks.
   - After 10 minutes, `backups/` holds today's file and `/api/health` shows it.
   - D's live check: lag under 20 ms while the Journal, OI pane and Portfolio are opened.
3. Hand the user `docs/plans/2026-10-sdk-operator-check.md` and stop until they report back. If a step fails, that is the next task, ahead of F.

---

## F. Send budget readout

### Goal
On Standard the desk lives inside 38 transactions and 54 requests a minute, with algos held to 30 transactions so a manual order always fits. When an algo waits, or a ticket is refused, the operator cannot see why. Show the budget.

### Docs first
- CONTEXT.md: **Send budget**: "The desk's share of Lighter's per-minute limits: requests and transactions in the last 60 seconds, against the desk's own caps." `_Avoid_: rate limit (for the desk's share), quota`.
- `docs/lighter-limits.md`: one paragraph on what the readout shows and what amber and red mean.

### Backend — `backend/src/mayedge/lighter/budget.py`
- `RestBudget.snapshot() -> dict` returns `{"type": "budget", "requests": n, "requests_cap": CAP, "tx": n, "tx_cap": TX_CAP, "algo_tx_cap": TX_CEILING["algo"], "cooling_until": ms or 0, "refused_60s": n}`. Count local refusals in the paths that raise `BudgetRefused`, in a 60s ring.
- Publish it at most once every 2 s, and only when it changed, from a small task started in `lifespan`. Add `"budget"` to `_REPLACE_TYPES` in `api/ws.py`, so a reconnecting tab gets the latest one. Also merge it into `GET /api/health`.
- The Kill lane is unchanged. Kill is still never refused.

### Web
- `web/src/components/widgets/Header.tsx`, the feed status: add one line to its tooltip, e.g. `Sends 12/38 · Requests 20/54 · last 60s`. Amber when sends reach the algo cap (30), red while cooling (`cooling_until` in the future), with "Lighter cooldown until 14:02:10 UTC". Keep times in UTC, as everywhere on the desk.
- Store it in `liveData.ts` next to the feed health, with the same subscribe/get pattern.

### Tests
- Backend: the snapshot counts txs and requests in the window and rolls them off; local refusals count; a venue 429 sets `cooling_until`; the publisher sends nothing when nothing changed.
- Web: the tooltip line renders, turns amber at 30 sends, turns red while cooling, and shows a UTC clock.

### Done when
`make ci` is green and the readout shows on the desk after ⏸ 2.

---

## G. Know when the desk was not watching

### Goal
Whenever the desk is not running, nothing on it runs: Trails do not follow, Planner's trailing parts hold, Auto kill does not check, and no Push goes out. The venue stops hold ([ADR 0015](../adr/0015-planner-owns-the-exit.md), [ADR 0016](../adr/0016-a-trail-is-moved-by-the-desk.md)), but the operator is never told. That is true wherever the desk runs: in local Docker during alpha, and on the VPS after it. A crash, an OOM kill, a deploy, a host reboot or a paused VM all look the same from the desk's side. **Nothing in this section may depend on the host being a laptop.** No sleep settings, no lid, no Docker Desktop specifics.

Three parts, each host-agnostic:

1. **On boot, say how long it was down.** The desk writes an "alive" mark to its own database every 30 s. At boot it reads the last mark, and the boot Push says how long the desk was gone and whether it stopped cleanly.
2. **On resume, say it was frozen.** A process that was paused and resumed (a VM pause, a host suspend, `SIGSTOP`) never restarts, so (1) cannot see it. The loop watch (D2) can: the wall clock jumped while the loop did not run.
3. **While down, someone else says so.** An optional outbound Heartbeat to a dead-man's-switch service, which messages the operator when the pings stop. Off unless `HEARTBEAT_URL` is set. On the VPS this is the part that matters most, because (1) and (2) only speak once the desk is back.

### Docs first
- `docs/adr/0019-the-desk-reports-its-own-absence.md`. It records:
  - The desk cannot report its own absence while it is absent. It reports a Down gap at boot and a Freeze on resume, and an outside service reports the rest from missing Heartbeats.
  - None of this depends on the host. The same code runs in local Docker and on the VPS.
  - The Heartbeat is outbound only (a GET to a URL the operator sets). There is still no public ingress ([ADR 0005](../adr/0005-no-app-auth-loopback-tailscale.md)).
  - The desk skips a ping when it is unhealthy, so the service's grace period does the alerting. The desk never pushes "I am fine".
  - Lighter's scheduled Cancel all (`CANCEL_ALL_TIF_SCHEDULED`) is **not** used as a dead man's switch: it would also cancel the venue stops that ADR 0015 and 0016 deliberately leave on while the desk is down.
- CONTEXT.md:
  - **Down gap**: "The time between the desk's last alive mark and its next boot." `_Avoid_: downtime, outage (for the desk; outage is the venue's)`.
  - **Freeze**: "A stretch when the desk process was paused and resumed without restarting." `_Avoid_: sleep, hang, stall (a stall is Loop lag)`.
  - **Heartbeat**: "A ping the desk sends a dead-man's-switch service while it is healthy." `_Avoid_: health check, keepalive`.
- `docs/push-rules.md`: the boot Push's new line, the Freeze Push, their keys and the `push.down_after_s` knob.
- README: under Pushes, "When the desk was not watching": the boot line, the Freeze Push, and the optional Heartbeat setup.

### G1. Down gap — `backend/src/mayedge/alive.py`
- Every 30 s, write `alive_at` (ms) to `meta`, through `asyncio.to_thread` and the writer under `db._lock`. On shutdown in `lifespan`, after `desk.stop()` and before `close_db()`, write `clean_stop_at`.
- At boot, before the first `alive_at` write, read the last `alive_at` and `clean_stop_at`. Down gap = boot time − `alive_at`. It is a clean stop when `clean_stop_at >= alive_at`.
- Knob in the `push:` block of `alerts.yaml`: `down_after_s: 60`. A shorter gap is a plain restart and the boot Push stays as it is today.
- Longer: extend the existing boot Push (`boot_text` in `push.py`, sent in `lifespan` with key `boot`). Do not add a second Push, and make it urgent:
  `Desk up (mainnet) after 2h 14m down (02:10–04:24 UTC, not a clean stop). Trails, Planner trailing parts and Auto kill were not watching; venue stops held. 3 algos restored, 2 Positions open.`
  "not a clean stop" becomes "clean stop" when it was one.
- Keep the last Down gap in `/api/health` as `last_down: {from, to, clean}` or `null`.
- A fresh database (no `alive_at`) is a first boot. Report no gap.

### G2. Freeze — extend `loop_watch.py` (D2)
- Each tick compares wall time elapsed with monotonic time elapsed. A wall jump of more than 30 s that the monotonic clock did not see is a **Freeze** from `last_wall` to `now_wall`. Do not assume which clock a given host stops during a pause. Test both directions: wall jumps with monotonic flat, and both jump. Count it only when the wall clock jumped and the loop missed the ticks.
- On a Freeze: publish `{"type": "desk_freeze", "from": ms, "to": ms}` through `publish` in `lifespan`, and keep the last one in `snapshot()` for `/api/health`.
- `push.py` → `PushRouter`: on `desk_freeze`, push urgently, key `freeze:{to}`:
  `Desk was frozen 14m (02:10–02:24 UTC). Trails, Planner trailing parts and Auto kill were not watching; venue stops held. 2 Positions open, uPnL −$120.`
  Read Positions and uPnL from the cached account payload. If the account feed is not live yet, say "Positions unknown until the account feed is back", and do not wait for it.
- Web: a `desk_freeze` message shows one toast with the same text. It is a fact, not an Alert ([ADR 0013](../adr/0013-an-alert-is-a-fact-and-a-toast-is-a-coincidence.md)).
- A plain loop stall (D) is not a Freeze: the monotonic clock advanced with the wall clock.

### G3. Heartbeat — `backend/src/mayedge/heartbeat.py`
- `Settings.heartbeat_url: str | None = None`. It is a secret: never logged, never in an API response, never in an error string. `/api/health` shows only `{"heartbeat": {"on": bool, "last_ok_at": ms}}`.
- Every 60 s, ping only when all of these hold: `market_ws == "live"`; `account_ws == "live"` if trading is enabled; `loop_lag_max_60s_ms < 2000`; no `venue_down_since`. Otherwise skip the ping and log at DEBUG why.
- `httpx.AsyncClient`, 10 s timeout, GET. The `httpx` logger is already at WARNING (`push.py`). Never log the URL or the request. On error, log one WARNING without the URL, at most every 10 minutes.
- It never touches the Lighter budget. It is not a Lighter call.
- Operator setup (README): any dead-man service that takes a ping URL works (Healthchecks.io, Cronitor, Better Stack). Suggested: period 2 min, grace 3 min, with the service's own Telegram integration pointed at the same chat as Pushes. Choosing the service is the operator's decision. The same URL works unchanged when the desk moves to the VPS.

### Tests
- `test_alive.py` with a temp DB and a fake clock: marks are written every 30 s; a boot 2 h after the last mark reports a 2 h gap that is not clean; a shutdown then boot reports a clean gap; a gap under `down_after_s` reports nothing; a fresh DB reports nothing; the write never runs on the loop (reuse `assert_loop_free` from D).
- `test_push.py`: the boot text with and without a gap, clean and not clean, and urgent only with a gap. `desk_freeze` pushes once, urgent, with the duration in `Xh Ym`, UTC times and the Position count. With the account feed not live it says "unknown" and still pushes.
- `test_loop_watch.py`: a 2 h wall jump with a 250 ms monotonic step is one Freeze with the right bounds; a 3 s loop stall is not a Freeze; two Freezes give two events.
- `test_heartbeat.py` with `httpx.MockTransport` and a fake clock: it pings every 60 s while healthy, skips on each unhealthy condition, sends nothing when the URL is unset, and the URL never appears in any log record (`assertLogs` at DEBUG on the root logger, the way `test_push.py` checks the token) or in `/api/health`.
- Web: the Freeze toast renders its text.

### Done when
`make ci` is green. ADR 0019, CONTEXT, push-rules and README are updated. ⏸ 2 shows the Down gap end to end.

---

## ⏸ 2. Rebuild, verify

Same as ⏸ 1, step 1 and step 2, plus:
- `/api/health` has `budget`, `heartbeat` (`on: false` unless the user set the URL), `last_down`, and the last Freeze (none yet).
- With the user's yes in chat: `docker compose stop`, wait 90 s, `docker compose start`. The boot Push says about 1m 30s down, clean stop, and `last_down` matches. Name the live algos in the same question, as in ground rule 8.
- Ask the user to hover the feed status and confirm the Send budget line.

---

## H. Batch probe on testnet (optional)

Run only if the user gives you testnet credentials for this, in a separate file, `backend/.env.testnet`. `.gitignore` does not cover that name today. Add `backend/.env.testnet` to it, and commit that, **before** the file exists.

### Question
On Standard, does one `sendTxBatch` of N orders count as **1 or N** against the 40 transactions a minute? If it is 1, a 20-rung Ladder or a Grid refill could go out as one send instead of twenty, which is the biggest win left on Standard. If it is N, batching saves only requests, and the desk stays as it is.

### Script `backend/scripts/probe_tx_batch.py`
- Takes `--env-file backend/.env.testnet` and builds its settings from that file **only** (`Settings(_env_file=path)`, with the process environment checked for stray `LIGHTER_*` variables), so `backend/.env`'s mainnet keys can never load. **Refuses to run unless `LIGHTER_NETWORK=testnet`**, and checks the resolved base URL itself, not just the variable.
- Picks a liquid testnet market and rests post-only limits 20% away from the touch at the venue minimum, so nothing fills.
- Run 1: single `sendTx` creates until the first 429 or 405. Record the count and the time.
- Wait 70 s (the 60 s firewall cooldown plus margin).
- Run 2: batches of 10 creates until the first 429 or 405. Record batches, orders and time.
- Cancel everything it created with one Cancel all, verify zero open orders, and print a table.
- Write the result into `docs/lighter-limits.md` with the date and the testnet market.

### Done when
The doc answers the question with numbers. If batches count as 1, write a short proposal (no code) at the end of the final report: which algo sends would batch, and what that does to the Standard budget. The user decides whether that becomes the next plan.

---

## Final report

When everything above is done, reply to the user with:
- The commits, one line each.
- The before and after numbers from D, and the live loop lag after ⏸ 1.
- E's SDK diff table.
- What the operator check (E5) and ⏸ 2 found, or that they are still waiting on the user.
- Anything found along the way and not fixed, with a failing test marked `expectedFailure` and a reason, or a line explaining why there is no test.

## Decisions the user still owes (defaults in place, so work can start)

| Decision | Default in this plan |
|---|---|
| Account tier | Standard, 0 fees (decided) |
| Python | 3.12 everywhere, matching the live desk |
| Backup location and count | `./backups` on the host, 7 daily |
| Heartbeat service | None: off until the user sets `HEARTBEAT_URL` with a service they choose |
| Host | Local Docker during alpha, the VPS after. Nothing in this plan depends on which; the VPS setup itself is not in this plan |
| Off-host Backup copy | After the VPS exists: Backups on the VPS should also leave it. Out of scope here |
| Batching sends | Not until H measures it on testnet |
