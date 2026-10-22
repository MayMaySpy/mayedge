# Hygiene plan — October 2026

Six pieces of upkeep from a code review on 2026-10-21, plus a list of things to leave until the code around them changes anyway. Nothing here adds a feature. Each section says what is wrong, what to build, where it goes, how to test it, and when it is done.

At the time of the review, ruff, basedpyright, oxlint and tsc were clean, 951 backend tests and 524 web tests passed, and `test_api_types.py` guarded the generated API types. This plan deals with duplicated code and fragile spots, not breakage.

| # | Work | Why | Size |
|---|---|---|---|
| A | Classify venue rejects once, by code | A reject can be misread as would-cross and dropped without a log | M |
| B | One set of algo helpers | `now_ms`, `_dec`, `_fmt` and order-key helpers copied up to six times, and `_dec` behaves differently in different copies | S–M |
| C | Put Trail and Planner books on the shared base | About 365 lines of `ClipBook` lifecycle copied twice | M–L |
| D | Enforce `ruff format` | It is configured but never checked; 85 files differ from its output | S |
| E | Make agent rules visible to every agent | The commit and typography rules live only in `.cursor/rules/` | S |
| F | Remove stray files at the root | An empty lockfile with no `package.json`, and stray test caches | S |
| G | Leave until the code is touched anyway | Package layout, API type coverage, singletons, broad excepts, two UI primitive libraries | — |

---

## 0. Ground rules

The ground rules in [2026-10-improvement-plan.md §0](2026-10-improvement-plan.md#0-ground-rules-read-before-any-section) apply in full. The ones that matter most here:

1. **Commit straight to `main`.** Small commits. Each message is one plain sentence ending in a period, followed by the `Co-Authored-By` line. Do not push unless asked.
2. **`make ci` is green before every commit.**
3. **The local desk is live mainnet in Docker.** Never place, amend or cancel an order on it to test anything. Test order flow with the fakes in `backend/tests/chase_harness.py` and `backend/tests/planner_harness.py`. Reading container logs is fine.
4. **Refactors do not change behaviour.** The exception is A, where the change is the point and is written down first. Any other behaviour change found along the way gets its own commit and its own test.
5. **The persisted format does not change.** `algo_type` ids, the columns in `algo_runs`, book counters and archived rows must still load from the live container's database. `test_restart.py` is the guard.

---

## A. Classify venue rejects once, by code

### Problem
The algos decide what a failed send means by searching the exception text. The helpers are in [`algos/chase/util.py`](../../backend/src/mayedge/algos/chase/util.py) (`_is_rate_limit`, `_is_order_not_found`, `_is_min_size`, `_is_would_cross`, `_is_invalid_nonce`). They have 43 call sites across chase, grid, ladder, planner, trail, twap and `lighter/orders.py`.

- `_is_would_cross` is true for any text containing `"post"` or `"cross"`. The lighter SDK's `ApiException.__str__` includes the HTTP response headers. A header like `Access-Control-Allow-Methods: GET, POST` or anything mentioning `cross-origin` would match. In [`grid/job.py`](../../backend/src/mayedge/algos/grid/job.py) `_modify` checks would-cross first and returns without logging, so a rate-limit or nonce error could be dropped there. Rate-limit and nonce errors are supposed to go to `_handle_tx_err`.
- `_is_min_size` matches `"min "` because [`orders.py` `_raise_order_err`](../../backend/src/mayedge/lighter/orders.py) rewrites code 21706 into `"Min 0.01 ETH or $10"`. So the algos decide what kind of error it is from wording written for the operator. Changing that wording would quietly break min-size handling.
- `lighter/orders.py` has its own copy of `_is_invalid_nonce`.
- The checks run in a different order at each call site.

### Docs first
Add an **Errors** section to [`docs/lighter-limits.md`](../lighter-limits.md). It is a table with one row per reason: the Lighter codes (from the [errors page](https://apidocs.lighter.xyz/docs/data-structures-constants-and-errors)), the text fallback (if any), what an algo does with it, and the test that pins it. Write the precedence order there as well. This table is the rule. The code follows it.

Before narrowing the text matching, collect the real messages that reach the algos today:

```bash
docker compose logs --since 720h mayedge 2>&1 | grep -iE "cross|post-only|nonce|not found|min |rate limit|2170|21104|23000" | sort | uniq -c | sort -rn | head -50
```

Every real would-cross message has to be in the test table, so that narrowing the match does not reclassify it as an unknown error.

### Build
In [`backend/src/mayedge/lighter/errors.py`](../../backend/src/mayedge/lighter/errors.py):

```python
class Reject(StrEnum):
    BLOCKED = "blocked"            # WAF / 429 / 23000 — today's venue_client_error
    INVALID_NONCE = "invalid_nonce"  # 21104
    ORDER_NOT_FOUND = "order_not_found"  # 21701
    MIN_SIZE = "min_size"          # 21706
    WOULD_CROSS = "would_cross"    # 2170x except 21701 / 21706
    ORDER_CAP = "order_cap"        # 21717, 21718, 21719, 21720
    # extend from the table, not ad hoc


class VenueReject(ValueError):
    """A send Lighter refused. ``str()`` is the operator's message; ``reason`` is for code."""

    def __init__(self, reason: Reject, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.code = code


def reject_reason(err: BaseException | str | None) -> Reject | None:
    """The one place a venue failure is classified. Order follows lighter-limits.md."""
```

Rules for `reject_reason`:
- A `VenueReject` returns its own `.reason`. It is never re-parsed.
- An `ApiException` (or any exception with `.status` / `.body`) is classified from status and body only, never from headers.
- A plain string or other exception is checked codes first, with `has_code` / `has_code_prefix`. Text fallbacks are exact phrases only: `"order not found"`, `"invalid nonce"`, `"post-only"`, `"would cross"`, and whatever the log sweep above turns up. Bare `"post"`, `"cross"` and `"min "` go away.
- `BudgetRefused` is never `BLOCKED`. This matches today's `_is_rate_limit`.
- `VenueBlocked` maps to `BLOCKED`.

`VenueReject` subclasses `ValueError`, so every `except ValueError` in `api/routes/*` keeps returning the same 400 with the same text. The UI does not change.

### Wire it in
1. `_raise_order_err` in `lighter/orders.py` raises `VenueReject(reason, <same message as today>, code)` instead of `ValueError`. Its `_is_invalid_nonce` helper calls `reject_reason`.
2. The five `_is_*` helpers in `algos/chase/util.py` become one-liners over `reject_reason`. This commit is where behaviour changes, and the only one.
3. Section B moves them and removes the leading underscores.
4. Make the precedence the same at every call site. Where a site checks would-cross before rate-limit or nonce (grid `_modify` and `_place`, chase `place.py`), the shared order now decides. A failure that is not classified is still logged, never swallowed.
5. Test fakes: `planner_harness.py:93` and `chase_harness.py:286` raise `VenueReject(...)` instead of strings that happen to match. Keep one string-raising fake per reason so the text fallback stays covered.

### Tests
New `backend/tests/test_venue_errors.py`, table-driven:
- Each code gives its reason. 21701 and 21706 are never `WOULD_CROSS`. Prices such as `64290.5` and order indices containing the digits match nothing (as `has_code` already ensures).
- An `ApiException(status=400)` whose headers mention `POST` or `cross-origin` and whose body says `invalid nonce` gives `INVALID_NONCE`, not `WOULD_CROSS`.
- A 429 `ApiException` with the same headers gives `BLOCKED`.
- Every message collected from the container logs gives the reason it should.
- `VenueReject` keeps its reason through `str()` and when re-raised.
- Grid `_modify`: a nonce error raised by the fake reaches `_handle_tx_err` and does not return quietly.

### Done when
- `rg '"post" in|"cross" in|"min " in' backend/src` returns nothing.
- `rg "def _is_(rate_limit|order_not_found|min_size|would_cross|invalid_nonce)" backend/src` finds at most the thin wrappers, which B then removes.
- The Errors table in `lighter-limits.md` names a pinning test on every row.
- `make ci` is green.

---

## B. One set of algo helpers

### Problem
| Helper | Copies | Divergence |
|---|---|---|
| `now_ms` | chase, grid, ladder `util.py`; `twap/job.py`; `feed_health._now_ms` | none, but tests have to patch each module (`chase_harness.patch_chase` patches two) |
| `_dec` | chase, grid, ladder `util.py`; `trail/state.py`; `planner/state.py`; `portfolio.py`; `lighter/liquidations.py` | chase and ladder raise on `None` or garbage; grid returns `0`; trail and planner return `None` |
| `_fmt` | chase, grid, ladder `util.py`; `ledger.py`; `planner/job.py`, `manage.py`, `entry.py`; `trail/job.py` | none — every copy just calls `numbers.fmt_decimal` |
| order keys | `_chase_order_keys`, `_ladder_order_keys`, `_grid_order_keys` | grid keeps rows with `order_index == 0` keyed by COI; chase and ladder drop them |
| `is_*_client_order` | chase, ladder | none (range check over the COI partition, [ADR 0004](../adr/0004-partitioned-client-order-index.md)) |

Five algos import underscore-private names from `chase/util.py`.

### Build
- **`mayedge/numbers.py`** (it already has `fmt_decimal` and `parse_decimal`):
  - `to_decimal(raw: object) -> Decimal` raises `ValueError` on `None` or anything it cannot parse. This replaces the chase and ladder `_dec`.
  - `to_decimal_or(raw: object, default: Decimal) -> Decimal`. This replaces grid's `_dec` (default `0`).
  - Trail and planner `state.py`, which want `Decimal | None`, call `parse_decimal` directly.
  - Call `fmt_decimal` directly. Delete every `_fmt` wrapper.
- **`mayedge/algos/common.py`** (new):
  - `now_ms() -> int`. Callers use `common.now_ms()`, through the module attribute, never `from ... import now_ms`, so tests patch one place.
  - `in_coi_range(coi: int | None, base: int, end: int) -> bool`.
  - `venue_order_keys(orders, accept: Callable[[int], bool], *, keep_unindexed: bool = False) -> list[tuple[int, int]]`. Grid passes `keep_unindexed=True` to keep its `oid or coi` behaviour.
- **Error helpers** from A: callers use `reject_reason(e) is Reject.X` directly, or public `is_would_cross(e)`-style helpers in `lighter/errors.py` where a short name reads better. No algo imports from another algo's `util.py`.
- **Delete** `chase/util.py`, `grid/util.py` and `ladder/util.py` once they are empty. Anything specific to one algo (`is_chase_client_order`) moves to that algo's `config.py`, next to its COI range.
- **Tests:** `chase_harness.patch_chase` patches `mayedge.algos.common.now_ms` once. Update `test_restart.py`, which patches the clock 9 times, and the other five test files that patch a clock or import a util.

### Order of commits
1. Add `numbers.to_decimal*` and `algos/common.py`, with unit tests (including grid's `keep_unindexed` case).
2. Move one algo per commit: chase, ladder, grid, twap, then planner and trail. Each `_dec` call site keeps the semantics it has today. If a site looks wrong (for example grid turning a missing price into `0`), note it in the commit body and fix it in its own commit with a test.
3. Delete the empty `util.py` files.

### Done when
- `rg "def (_?now_ms|_dec|_fmt)\(" backend/src` finds only `numbers.py` and `algos/common.py`.
- `rg "from mayedge.algos.\w+.util import _" backend/src` returns nothing.
- `make ci` is green.

---

## C. Put Trail and Planner books on the shared base

### Problem
`ChaseBook`, `LadderBook`, `AdvancedTwapBook` and `ChaseGridBook` all extend [`ClipBook`](../../backend/src/mayedge/algos/clip_book.py). [`TrailBook`](../../backend/src/mayedge/algos/trail/book.py) and [`PlannerBook`](../../backend/src/mayedge/algos/planner/book.py) don't. Each carries its own copy of the lifecycle: id/COI counters, `alloc_id`, `alloc_coi`, `_persist`, `publish`, `finish`, `flush`, `restore`, `_archive_broken`, `drain_for_shutdown`, `pause`/`unpause`/`stop` and `pause_for_market`. `_save_counters`, `alloc_coi`, `_wait_feeds_ready`, `restore` and `_archive_broken` are line-for-line the same in trail and planner. A restore fix has to be made three times.

Differences that have to survive:
- **Feed wait.** `ClipBook._wait_feeds_ready(market_indices)` also waits for `is_book_synced` on every restored market. Trail and planner wait only for the account feed and hydrated orders.
- **Extra wiring in trail and planner:** `set_market_conflict`, `set_watch_prints`, `take_amend`, `_sync_watch` (called after restore and on finish) and `_check_free`.
- **Extra entry points:** trail has `preview_from_body`, `start_from_body` and `edit_from_body`; planner has `preview_from_body`, `start_from_body`, `replan_from_body` and `finish_entry`. ClipBook books start through `_launch` and `_ensure_book`.
- `TrailBook` imports `mayedge.algos.planner.venue`, so trail depends on planner. Decide whether `venue` belongs in `algos/common.py` (B) or stays where it is, and write the decision in the commit.

### Build
1. **Write down the differences first.** Diff the three files method by method. Commit the result as a short table at the top of `clip_book.py`'s module docstring: which methods are shared, which are hooks, and which belong to one book only.
2. **Split `ClipBook`** into:
   - `AlgoBook[R]` (new, in `algos/algo_book.py` or the same file): counters, alloc, persist, publish, finish, flush, restore, archiving, drain, pause/unpause/stop, pause-for-market and the feed wait. Hooks with defaults that do nothing:
     - `_new_runner() -> R`
     - `_restore_needs_books() -> bool` (ClipBook returns `True`; trail and planner `False`)
     - `_on_restored(job)` and `_on_finished(job)` (trail and planner call `_sync_watch`)
   - `ClipBook[R](AlgoBook[R])`: what is left that only clip books need (`_ensure_book`, `_launch`, `live_on_market_side`, `missing_fill_grace_ms`).
3. **Move `TrailBook` onto `AlgoBook`** in one commit. Delete its copied methods. Keep the trail-only ones.
4. **Move `PlannerBook`** the same way, in its own commit.
5. If `set_market_conflict`, `set_watch_prints`, `take_amend` and `_check_free` turn out to be the same in both, lift them into a small mixin. Otherwise leave them.

### Tests
- The existing tests are the guard: `test_restart.py` (every algo), `test_trail_job.py`, `test_planner_job.py`, `test_planner_plan.py` and `test_chase_runner.py`.
- Add one restore test per book that loads rows written by the **current** code (a fixture captured before the refactor) and checks they come back with the same ids, the same COI counters and the same status. This is the persisted-format guard from ground rule 5.
- Add one test that a trail and a planner restore without waiting for order-book sync, as they do today.

### Done when
- `trail/book.py` and `planner/book.py` hold only what is specific to trail or planner. Expect each under about 150 lines.
- `rg "def (_save_counters|alloc_coi|_archive_broken|_wait_feeds_ready)" backend/src/mayedge/algos` finds them in one file.
- `make ci` is green, and a restart of the local desk (`make up`) restores live algos, if any are running. Check this in the UI and logs only. Place nothing.

---

## D. Enforce `ruff format`

### Problem
`[tool.ruff.format]` is configured in `backend/pyproject.toml`, but neither CI nor `make ci` runs it. `uv run ruff format --check src tests` reports 85 files that would be reformatted (about 1,300 changed lines). New code drifts further every week.

### Build
1. One commit that only formats: `cd backend && uv run ruff format src tests scripts`. Message: "Format the backend with ruff format."
2. Add that commit's SHA to a new `.git-blame-ignore-revs` at the repo root, with a comment line. Run `git config blame.ignoreRevsFile .git-blame-ignore-revs` locally. GitHub reads the file on its own.
3. Add `uv run ruff format --check src tests scripts` to `ci-backend` in the `Makefile` and to the backend job in `.github/workflows/ci.yml`, next to `ruff check`. Extend `ruff check` to `scripts` at the same time.
4. Web: no formatter is set up today. Adding one (oxfmt or Prettier) is out of scope unless the operator wants it. If so, do it the same way: one formatting commit, an ignore-revs entry and a CI check.

### Do this first
Do D before A, B and C, so the refactors' diffs are not mixed with formatting changes.

### Done when
- `make ci-backend` fails on a file that isn't formatted.
- `git blame` on a reformatted line shows the earlier author.

---

## E. Make agent rules visible to every agent

### Problem
The "run `make ci` before every commit" rule and the desk type scale live only in `.cursor/rules/commit.mdc` and `.cursor/rules/typography.mdc`, which only Cursor reads. The ground rules every agent needs (commit to main, the local desk is live mainnet, one viewer, Auto kill watches only uPnL) live in a plan document. There is no `CLAUDE.md` or `AGENTS.md`.

### Build
A short root `CLAUDE.md`, under about 40 lines, that imports rather than copies:

```markdown
# Mayedge

Read [CONTEXT.md](CONTEXT.md) for the desk's words; bold words mean what it says.

@.cursor/rules/commit.mdc
@.cursor/rules/typography.mdc

## Ground rules
- Commit straight to main; one plain sentence per message. Push only when asked.
- The local desk (:14200) is live mainnet. Never place, amend or cancel an order to test. Use the harness fakes.
- Rules before code: change docs/*-rules.md, the code and its pinning test in one commit (ADR 0011).
- One viewer. Auto kill watches uPnL only, on purpose.
- Secrets live in backend/.env only.
```

- Keep `.cursor/rules/` as the source, so Cursor still works and nothing is duplicated.
- Do not add a `CONTRIBUTING.md`; `commit.mdc` says so.
- If another agent that only reads `AGENTS.md` comes into use, make `AGENTS.md` the source and have `CLAUDE.md` contain `@AGENTS.md`.

### Done when
A fresh Claude Code session in the repo can state the commit rule and the live-mainnet rule without being told.

---

## F. Remove stray files at the root

| Item | State | Action |
|---|---|---|
| `package-lock.json` (root) | Tracked, 86 bytes, `"packages": {}`, and there is no root `package.json` | `git rm` |
| `node_modules/` (root) | Untracked, gitignored, holds only `.vite` and `.vitest` caches from running tests at the root | `rm -rf node_modules` locally. Nothing to commit |
| `backend/src/**/__pycache__` | Ignored, holds stale `chase_*.cpython-314.pyc` from modules split long ago, and pyc files for both 3.12 and 3.14 | `find backend -name __pycache__ -prune -exec rm -rf {} +` locally. Nothing to commit |
| `skills-lock.json`, `.agents/skills/` | Tracked shadcn agent skills | Keep. They are intentional |
| `.claude/launch.json` | Tracked preview config | Keep |

### Done when
`git ls-files | grep -c '^package-lock.json$'` is `0`, and `make ci` is still green.

---

## G. Leave until the code is touched anyway

These are real, but none is worth a commit of its own now. Each row says what should prompt the change.

| Item | Today | Do it when |
|---|---|---|
| Flat backend package | About 45 modules at `mayedge/`, grouped only by prefix: `alert_*`, `push_*`, `persist_*`, `journal_*`, `portfolio_*`, `tone_*` | A group gets a new module. Then move that group into a subpackage (`mayedge/push/…`) in one commit with only the move, and keep a re-export shim for one release if tests import the old path |
| Generated API types | [`api.ts`](../../web/src/lib/api.ts) has 47 hand-written interfaces. Only journal, portfolio and order requests come from `api.gen.ts` | A route in `markets`, `account` or `algos` changes shape. Give it a pydantic response model in `api/responses.py`, run `make api-types`, and delete the hand-written interface |
| Module-level singletons | The books in `desk.py`, `db._conn`, `settings`, `budget`, `ws.manager`, and 35 `global` statements | Leave as is. One process and one viewer make this a fair trade. Revisit only if tests start needing to reset state between cases |
| 164 `except Exception` | Most re-classify or log, which suits code that talks to the venue | After A, check the algo ones. Any that neither logs nor re-raises should log. Not a refactor of its own |
| Two UI primitive libraries | Radix behind 14 `components/ui/*` primitives, Base UI only behind `combobox.tsx` (the `migrate-radix-to-base` skill is installed) | You want a Base UI feature in another primitive. Then migrate one primitive per commit. Not a sweep |
| Backend test speed | 951 tests in about 17s at about 40% CPU, which suggests real sleeps | It passes about 30s. Then find the slow ones (`python -m unittest -v` with timing) and use the harness clock |

---

## Order and parallel work

```
D  ──►  A  ──►  B  ──►  C
E, F: any time, independent
```

- **D first.** It touches 85 files, and every later diff should be free of formatting changes.
- **E and F** don't touch Python or TypeScript and can go in any time, even in the same sitting as D.
- **A before B.** B moves the error helpers that A rewrites. Moving them first would mean changing the same lines twice.
- **C after B.** Both edit `algos/`, and C's books import from the helpers B moves. They could run side by side in separate worktrees, but there is little to gain and a likely merge conflict in `clip_book.py`.
- Each lettered section is a run of small commits on `main`, each green on `make ci`. Expect about 15–20 commits in all.
