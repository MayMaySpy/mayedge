# Ideas — the watchlist page, scope

Keep the Markets the operator wants to trade, and **why**: the narrative, the catalysts, and a plan of where to enter, where it is wrong, and where to take profit. Track each one against live price until it is traded, then review it against the Round trips it became.

Placement: an `/ideas` page, like `/portfolio` and `/journal`, opened from a new **Ideas** button in the desk header. From an Idea the operator can put its plan on the chart as a **Draft**, and start a **Planner** from there. Nothing else on the page reaches the venue.

Read [the October plan](2026-10-improvement-plan.md) §0 first. Its ground rules hold here: rules doc before code ([ADR 0011](../adr/0011-alert-rules-are-written-down-before-they-are-coded.md)), commit straight to `main`, `make ci` green before every commit, and never place, amend or cancel an order on the live desk to test. This feature **writes only to the desk database**. It sends nothing to the venue.

---

## 0. The name (decide before step 1)

The operator asked for a "watchlist". [CONTEXT.md](../../CONTEXT.md) already uses **Watchlist** for something else: the Markets in a **Watch Set** on the Watch view (cap 8, no notes). Reusing the word would make every rule ambiguous. This scope uses **Idea** for one tracked Market and **Ideas** for the page.

> Decided unless the operator says otherwise: the page is **Ideas** at `/ideas`. If they want the word "Watchlist" on it, the Watch view's term moves to **Watch Set Markets** in CONTEXT.md in the same commit, and every use in code, docs and tests moves with it. Do not ship two meanings.

---

## 1. Words (add to CONTEXT.md, section "Ideas", after "Execution")

**Idea**:
A Market the operator wants to trade, with a Thesis and, once written, a Plan. One side: long or short. It never sends an order. The rules are in [docs/idea-rules.md](docs/idea-rules.md).
_Avoid_: Watchlist (that is a Watch Set's Markets), setup, signal, call, trade (a trade is a fill)

**Thesis**:
Why the Idea should work: the narrative in the operator's words, its Catalysts and its tags. Required to save an Idea.
_Avoid_: reason, note (unqualified; a Round trip's note is the Journal's), narrative (for the whole of it)

**Catalyst**:
A dated event the Thesis leans on: an unlock, a listing, a mainnet, a vote. Date in UTC, optional.
_Avoid_: event (unqualified), news

**Plan**:
An Idea's Entry, Stop and Targets, and the Trigger that says when to enter. Prices only. Size is the Planner's job.
_Avoid_: plan (lowercase, unqualified: that is the Planner algo), Draft (that is the chart's), setup, bracket

**Entry zone**:
The price range the Plan enters in, `low`–`high`. A single price is a zone with `low = high`. Its **plan entry** is the midpoint: R, R multiples and the Draft all use it.
_Avoid_: entry (unqualified, that's the Planner's), buy zone, area

**Trigger**:
The operator's words for what must happen before entering ("4h close back above 2.30"). The desk does not read it.
_Avoid_: condition, signal, Activation (that is a Trail's)

**Invalidation**:
What proves the Thesis wrong. The Plan's stop price is the price part of it; the text says the rest ("unlock moved earlier", "BTC loses 58k").
_Avoid_: stop (for the text), stop loss

**In zone**:
An Idea whose Market's Last is inside its Entry zone. A fact on the page; it raises nothing in v1.
_Avoid_: triggered, ready, hit

**Past stop**:
A Watching Idea whose Last is beyond its stop. The page flags it. The operator drops it or moves the stop; the desk never does.
_Avoid_: invalidated (only the operator invalidates), stopped out (that is a fill)

**Idea log**:
The Idea's timestamped lines: the operator's updates, and one line each time the Plan or the status changes, with Last at that moment. Append only.
_Avoid_: history, journal (that is the Journal page), comments

**Review**:
How an Idea ended, written when it is Closed or Dropped: an outcome and what the operator learned.
_Avoid_: post-mortem, result (that is the Round trips' Net)

Status words go in the rules doc (§3), not the glossary.

---

## 2. What already exists and gets reused

| Piece | Where | Use here |
|---|---|---|
| Page shell, REST-only page, nav | `components/PortfolioPage.tsx`, `components/PageNav.tsx`, `lib/deskRoute.ts`, `App.tsx` | Same shell, same lazy import, add `IDEAS_PATH`, `isIdeasPath`, `"IDEAS"` in `RESERVED`, add Ideas to `PAGES`. |
| Header page buttons | `components/widgets/Header.tsx` (Portfolio, Journal, ~line 516) | Third button **Ideas**, `Lightbulb` icon, `target="_blank"`. |
| Free-text notes stored per key | `persist_journal.py` `journal_notes`, `api/routes/journal.py` `NoteBody` | Same pattern: SQLite row, tags as JSON text, `updated_at` in s. |
| Numbered migrations | `migrations.py` (`LATEST` = 15) | Step 16 "ideas". Never edit a shipped step. |
| API types | `api/schemas.py`, `api/responses.py`, `make api-types` → `web/src/lib/api.gen.ts` | Request and response shapes; regenerate, never hand-edit `api.gen.ts`. |
| Market list, in memory | `gateway.list_markets()` → `GET /api/markets` | Live Last, Daily Change, funding, day high/low for each Idea. No venue call. |
| Candles | `GET /api/candles/{symbol}` | The mini chart on the detail panel. |
| Round trips | `api.journalTrips({ market, since })`, `JournalTrip.open_ts/close_ts/net/r` | An Idea's trades, with no backend change. |
| Draft on the chart | `lib/chartDraft.ts` (`ChartDraft`, `requestChartDraftOpen`, `draftRAt`, `draftTargetPrice`) | An Idea hands its Plan to the desk as a Draft ([ADR 0018](../adr/0018-the-chart-drafts-a-planner.md)). |
| Desk ↔ other tab channel | `lib/deskBridge.ts` (`BroadcastChannel("mayedge-desk")`, `isDeskMessage`, `useDeskWatchBridge`) | Two new messages: a ping and the Draft hand-off (§6). |
| Market picker, token icon | `widgets/MarketPicker.tsx`, `desk/TokenMark.tsx`, `ui/combobox.tsx` | New Idea dialog, list rows. |
| Formatting | `lib/journalFormat.ts` (`money`, `price`), `lib/marketFormat.ts`, `lib/utcTime.ts` | Every number and time on the page. |
| UI primitives | `ui/table`, `ui/textarea`, `ui/dialog`, `ui/toggle-group`, `ui/badge`, `ui/empty`, `ui/field`, `ui/dropdown-menu`, `ui/sheet` | Nothing new from shadcn is needed. |

---

## 3. Rules (write `docs/idea-rules.md` first, in the step-1 commit)

Same form as the other rules docs: a numbered table, "code" when a number is not a knob, and the test that pins it. Draft:

### Shape

| | Rule | Pinned by |
|---|---|---|
| I1 | An Idea is one Market, by symbol, and one side. The symbol is stored upper case. A symbol the venue no longer lists keeps its Idea; the page shows "Not listed" and no price. | `test_an_unlisted_market_keeps_its_idea` |
| I2 | An Idea cannot be saved without a Thesis of at least 10 characters after trimming. Everything else is optional at creation. | `test_an_idea_needs_a_thesis` |
| I3 | More than one Idea per Market is allowed (a long and a short, or a new one after a Closed one). The page warns when a second **open** Idea (Watching or Active) is made on the same Market and side. | `test_a_second_open_idea_on_a_market_warns` |
| I4 | Tags are lower case, trimmed, 1–24 characters, at most 8 per Idea, de-duplicated. They are the narratives ("ai", "l2", "rwa", "unlock"). | `test_tags_are_normalised` |
| I5 | Catalysts are at most 12 per Idea: text up to 120 characters and an optional UTC date. Sorted by date, undated last. | `test_catalysts_sort_by_date` |
| I6 | Prices are stored as decimal strings, as typed, and never as floats. | `test_prices_round_trip_as_typed` |

### Plan

| | Rule | Pinned by |
|---|---|---|
| P1 | A Plan has an Entry zone (`entry_low`, `entry_high`), a stop and 0–4 Targets. A single entry price is stored as `low = high`. `low ≤ high`, all > 0. | `test_a_zone_is_low_then_high` |
| P2 | Long: the stop is below `entry_low`, every Target is above `entry_high`. Short: the mirror. A Plan that breaks this is refused with the field that breaks it. | `test_a_long_stop_sits_below_the_zone`, `test_a_short_target_sits_below_the_zone` |
| P3 | The plan entry is the zone's midpoint. **R** = |plan entry − stop|. A Target's R multiple is its distance from the plan entry over R, to 2 places. | `test_targets_are_measured_from_the_midpoint` |
| P4 | A Target is stored as a price. The editor accepts an R multiple and converts it to a price at the Market's `price_decimals`, using P3. | `web: ideas.test.ts` |
| P5 | Target sizes are optional %s of the Position that add up to 100 or less, like the Planner's. Without them the Draft gets the Planner's default split. | `test_target_shares_add_up_to_100_or_less` |
| P6 | A Plan is complete with a zone and a stop. Only a complete Plan can go to the chart (D1). | `test_a_plan_needs_a_zone_and_a_stop` |

### Status

| | Rule | Pinned by |
|---|---|---|
| S1 | Status is one of **Watching**, **Active**, **Closed**, **Dropped**. A new Idea is Watching. | `test_a_new_idea_is_watching` |
| S2 | Watching → Active when the operator marks it, or when a Planner is started from its Draft (D4). Active → Closed by the operator. Watching or Active → Dropped by the operator. Closed or Dropped → Watching is a reopen. No other move. | `test_status_moves` |
| S3 | The desk never moves a status on price. In zone and Past stop are shown, never acted on. | `test_price_never_moves_a_status` |
| S4 | Every status move and every Plan change writes one Idea log line, with Last at that moment if the desk has one. A Plan change line names what moved: `Stop 2.08 → 2.12`. | `test_a_plan_change_is_logged` |
| S5 | Closed and Dropped Ideas ask for a Review: outcome **Worked**, **Failed**, **Missed** (never entered, it went without us) or **Wrong** (invalidated before entry), and free text. Optional, editable later. | `test_a_review_is_optional` |
| S6 | Delete removes an Idea and its log for good. The page asks first and names the Idea. Dropped is the normal way out. | `test_delete_removes_the_log` |

### Live (all on the page, from `GET /api/markets`)

| | Rule | Pinned by |
|---|---|---|
| L1 | Last is the Market's last trade, else mark, else mid, as in CONTEXT.md. Missing is unknown, not `0`. | `web: ideas.test.ts` |
| L2 | **To entry** is the signed % from Last to the nearest zone edge, over Last: `0` inside the zone. Long above the zone and short below it are positive (price must come back); the other side is negative (price must go through). | `web: ideas.test.ts` |
| L3 | **In zone**: `entry_low ≤ Last ≤ entry_high`. A single price counts as in zone within 0.25% of it (code). | `web: ideas.test.ts` |
| L4 | **Past stop**: a Watching Idea whose Last is at or beyond its stop. | `web: ideas.test.ts` |
| L5 | **R now**: for an Active Idea, (Last − plan entry) / R, signed by side. Unknown without a complete Plan. | `web: ideas.test.ts` |
| L6 | The page reads `/api/markets` every 10 s while visible, and the Ideas every 60 s and after each save. It opens no desk socket ([ADR 0001](../adr/0001-watch-is-a-desk-view.md), portfolio W1). | `IdeasPage` tests |

### Draft hand-off

| | Rule | Pinned by |
|---|---|---|
| D1 | **Draft on chart** sends one message on the desk channel: symbol, side, plan entry, stop, Targets as R multiples with their %s, and the Idea id. Only for a complete Plan (P6). | `deskBridge` tests |
| D2 | The desk answers a ping within 500 ms when its tab is open. Without an answer, the page opens the desk at `/{SYMBOL}` in a new tab and sends the Draft once that tab says hello. One desk tab, never two (CLAUDE.md: one viewer). | `IdeasPage` tests |
| D3 | The desk switches to the Market, replaces that Market's Draft with the Idea's (a toast says so when it replaced one), and opens the Planner dialog. Nothing reaches the venue until **Start** ([ADR 0018](../adr/0018-the-chart-drafts-a-planner.md)). A Market where a Planner already runs shows the dialog's own refusal ([ADR 0015](../adr/0015-planner-owns-the-exit.md)). | `chartDraft` tests |
| D4 | When a Planner starts from that Draft, the desk writes `POST /api/ideas/{id}/planner` with the algo id. The Idea goes Active (S2) and its log names the Planner. If the write fails, the Planner still runs; a toast says the Idea was not updated. | `test_a_planner_start_marks_the_idea_active` |
| D5 | An Idea's Round trips are the Journal's on its Market whose `open_ts` is at or after the Idea's creation, and before it was Closed or Dropped if it was. | `web: ideas.test.ts` |

Add `docs/idea-rules.md` to the CONTEXT.md entry for **Idea** and to the README's docs list if it has one.

---

## 4. ADR 0020 — An Idea is a note, not an order

Write `docs/adr/0020-an-idea-is-a-note-not-an-order.md` in the step-1 commit:

> The Ideas page writes only to the desk database. Its one path toward the venue is the Draft hand-off: it gives the desk a Draft, and the operator starts the Planner from the desk as they would from a Draft drawn by hand. No price on the page triggers anything. A "buy when it reaches the zone" would be a second way to place orders, with no Planner dialog in front of it, on a page that is not the desk. If that is ever wanted, it is a Trail entry or a Planner, started from the desk.

---

## 5. Backend

### Migration (step 16, `migrations.py`, plus `db._SCHEMA` for new files)

```sql
CREATE TABLE IF NOT EXISTS ideas (
    id TEXT PRIMARY KEY,                -- "idea-" + 12 hex, made by the server
    symbol TEXT NOT NULL,               -- upper case (I1)
    side TEXT NOT NULL,                 -- 'long' | 'short'
    status TEXT NOT NULL,               -- 'watching' | 'active' | 'closed' | 'dropped'
    conviction INTEGER NOT NULL DEFAULT 2,  -- 1..3
    horizon TEXT NOT NULL DEFAULT 'swing',  -- 'scalp' | 'swing' | 'position'
    thesis TEXT NOT NULL,
    invalidation TEXT NOT NULL DEFAULT '',
    trigger TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',        -- JSON list (I4)
    catalysts TEXT NOT NULL DEFAULT '[]',   -- JSON list of {text, date|null} (I5)
    entry_low TEXT,                         -- decimal strings (I6); null until planned
    entry_high TEXT,
    stop TEXT,
    targets TEXT NOT NULL DEFAULT '[]',     -- JSON list of {price, pct|null}
    planner_ids TEXT NOT NULL DEFAULT '[]', -- JSON list of algo ids (D4)
    outcome TEXT,                           -- S5, null until reviewed
    review TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,            -- ms
    updated_at INTEGER NOT NULL,            -- ms
    closed_at INTEGER                       -- ms, set on Closed or Dropped, cleared on reopen
);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status, updated_at);

CREATE TABLE IF NOT EXISTS idea_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id TEXT NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    ts INTEGER NOT NULL,                    -- ms
    kind TEXT NOT NULL,                     -- 'update' | 'plan' | 'status' | 'planner'
    body TEXT NOT NULL,
    last TEXT                               -- Last at ts, decimal string, null if unknown
);
CREATE INDEX IF NOT EXISTS idx_idea_log ON idea_log(idea_id, ts);
```

All times in **ms** (the journal shipped with mixed s and ms once; do not repeat it). `journal_notes.updated_at` is in s; do not copy that. `db.py` turns `PRAGMA foreign_keys` on, so the cascade does S6. Add the step to `test_migrations.py`. Backups need nothing: they copy the whole file.

### Modules

- `backend/src/mayedge/ideas.py` — pure, no I/O.
  - `Idea`, `Target`, `Catalyst` dataclasses with `Decimal` prices.
  - `normalise(body) -> Idea | Refusal`: I2, I4, I5, P1, P2, P5. A Refusal names the field and says why in one plain sentence, as the Planner's do.
  - `plan_entry(idea) -> Decimal | None`, `r_of(idea)`, `r_multiples(idea)` (P3).
  - `move(status_from, status_to) -> bool` (S2).
  - `plan_diff(before, after) -> str` (S4): `"Entry 2.30–2.35 → 2.28–2.33 · Stop 2.08 → 2.12"`, empty when nothing in the Plan moved.
- `backend/src/mayedge/persist_ideas.py` — SQLite rows, like `persist_journal.py`.
  - `ideas_list(status: str | None) -> list[dict]`, `idea_get(id)`, `idea_insert`, `idea_update`, `idea_delete`, `idea_log_add(idea_id, kind, body, last)`, `idea_log(idea_id)`.
  - Each write that changes the Plan or the status adds its log line **in the same transaction**.
- `backend/src/mayedge/api/routes/ideas.py`, registered in `api/routes/__init__.py`. Every handler runs its SQLite work with `asyncio.to_thread`, as the journal routes do. The route reads Last from `gateway.get_market(symbol)` for log lines (L1); it never calls the venue.

### API

| Method | Path | Body | Answer |
|---|---|---|---|
| GET | `/api/ideas?status=watching\|active\|closed\|dropped\|open\|all` | — | `{ideas: Idea[]}`, newest `updated_at` first. `open` = Watching + Active. Default `open`. |
| GET | `/api/ideas/{id}` | — | `{idea: Idea, log: IdeaLogLine[]}` |
| POST | `/api/ideas` | `IdeaBody` | `{idea, warning?}` (I3 warning). 422 with the Refusal. |
| PATCH | `/api/ideas/{id}` | partial `IdeaBody` (no status) plus `seen_updated_at` | `{idea}`. Plan changes log (S4). 409 when `seen_updated_at` is older than the row (§10, autosave races). |
| POST | `/api/ideas/{id}/status` | `{status, outcome?, review?}` | `{idea}`. 409 for a move S2 does not allow. |
| PATCH | `/api/ideas/{id}/review` | `{outcome?, review?}` | `{idea}` |
| POST | `/api/ideas/{id}/log` | `{body}` (1–2,000 chars) | `{line}` |
| POST | `/api/ideas/{id}/planner` | `{algo_id}` | `{idea}` (D4). Idempotent per algo id. |
| DELETE | `/api/ideas/{id}` | — | `204` (S6) |

`Idea` in answers carries the stored fields plus `plan_entry`, `r` and `r_multiples` (strings, null when the Plan is not complete), so web and backend never disagree on P3. Live fields (L2–L5) are computed on the page from `/api/markets`, because they move every 10 s.

Put `IdeaBody`, `IdeaStatusBody`, `IdeaReviewBody`, `IdeaLogBody`, `IdeaPlannerBody` in `api/schemas.py` and the answers in `api/responses.py`, then `make api-types`. `test_api_contract.py` and `test_api_types.py` will tell you if a shape drifted.

Access: the desk has no app auth ([ADR 0005](../adr/0005-no-app-auth-loopback-tailscale.md)). `api/guard.py` is middleware: it already checks Host on every request and Origin on every write, so the Ideas routes are covered with no extra code. Add one case to `test_browser_guard.py` that a foreign Origin cannot `POST /api/ideas`.

---

## 6. Web

### Files

| File | What |
|---|---|
| `lib/deskRoute.ts` | `IDEAS_PATH = "/ideas"`, `isIdeasPath`, `"IDEAS"` in `RESERVED`. |
| `App.tsx` | Lazy `IdeasPage`, like `PortfolioPage`. |
| `components/PageNav.tsx` | `{ name: "Ideas", path: IDEAS_PATH }` after Journal. |
| `components/widgets/Header.tsx` | **Ideas** button after Journal, `Lightbulb` icon. |
| `lib/api.ts` | `api.ideas(status)`, `api.idea(id)`, `api.ideaCreate`, `api.ideaPatch`, `api.ideaStatus`, `api.ideaReview`, `api.ideaLog`, `api.ideaPlanner`, `api.ideaDelete`. Types come from `api.gen.ts`. |
| `lib/ideas.ts` | Pure: L1–L5, D5, P4 (R ↔ price), `ideaToDraft(idea, decimals) -> ChartDraft` (D1), sort keys, the zone-bar geometry (below). All unit-tested. |
| `hooks/useIdeasPage.ts` | Load and refresh (L6), selection, filters, optimistic saves with rollback and `notifyErr`. Same shape as `usePortfolioPage`. |
| `components/IdeasPage.tsx` | The page shell. |
| `components/ideas/IdeaList.tsx` | The list (left). |
| `components/ideas/IdeaDetail.tsx` | The detail (right): header, zone bar, mini chart, Thesis, Plan, Log, Trades, Review. |
| `components/ideas/IdeaPlanForm.tsx` | The Plan editor. |
| `components/ideas/NewIdeaDialog.tsx` | Create. |
| `components/ideas/IdeaZoneBar.tsx` | The price ruler (SVG). |
| `components/ideas/IdeaChart.tsx` | Mini candle chart with the Plan's lines (`lightweight-charts`). |
| `lib/deskBridge.ts` | `desk-ping`, `desk-pong`, `idea-draft` messages (§6 "Draft hand-off"). |
| `lib/chartDraft.ts` | `setChartDraft(symbol, draft)` and a per-Market `draftIdea` id, cleared with the Draft. |

### Page layout (`/ideas`, lg and up: one viewport, like the Portfolio)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ← Desk  Portfolio  Journal  Ideas        [Open|Watching|Active|Closed|Dropped|All] [Nearest entry▾] [⌕] [+ New idea] │
├──────────────────────────────────────────────────────┬───────────────────────────────────────────────────┤
│ IDEA LIST                                            │ IDEA DETAIL                                       │
│ Market  Side  Last    24h    To entry  R:R  Conv Upd │ ZRO  LONG  Watching  ●●●  Swing  [Draft on chart] ⋯│
│▍ZRO     L     2.214  +3.1%   In zone   3.4  ●●●  2m  │ Unlock overhang gone after the 20th; L0 points…   │
│ ENA     S     0.412  −1.2%   +4.8%     2.1  ●●○  1h  │ ┌ zone bar ───────────────────────────────────┐   │
│ TIA     L     6.02   +0.4%   −2.3%     —    ●○○  3d  │ │ stop┃   ▐ zone ▌  ▲Last   T1┃   T2┃    T3┃  │   │
│ HYPE    L     —      —       Not listed     ●●○  9d  │ └─────────────────────────────────────────────┘   │
│                                                      │ ┌ chart ─────────────────────── [1h 4h 1d] ┐      │
│                                                      │ │ candles; ZONE, STOP, T1–T3 as price lines │      │
│                                                      │ └───────────────────────────────────────────┘      │
│                                                      │ Thesis │ Plan │ Log 12 │ Trades 2 │ Review         │
│                                                      │ … the chosen tab …                                │
└──────────────────────────────────────────────────────┴───────────────────────────────────────────────────┘
```

Grid: `lg:grid-cols-[minmax(520px,1fr)_560px]`, both columns scroll on their own (`lg:min-h-0 lg:overflow-y-auto`), page shell exactly as `PortfolioPage` (`h-dvh`, `max-w-[1680px]`, `p-4`, `gap-3`, `panel` sections). Under `lg` the list is the page; selecting an Idea opens the detail in a right `Sheet` at full width with a back arrow.

URL keeps the state that should survive a reload: `/ideas?id=idea-…&status=open&sort=entry`. Read with `URLSearchParams`, write with `history.replaceState`. `document.title` = `Ideas` or `ZRO long · Ideas` when one is selected.

### Header row

- `PageNav current="Ideas"`.
- Status filter: `ToggleGroup` single, `h-6 px-2 text-xs`, values **Open** (default) · Watching · Active · Closed · Dropped · All. Each item shows its count in `text-muted-foreground` (`Watching 7`).
- Sort: `Select`, `h-6`: **Nearest entry** (default for Open/Watching: in-zone first, then smallest |To entry|), Conviction, Catalyst soonest, Updated, Created, Market A–Z. Closed/Dropped default to Updated.
- Search: `Input` `h-6 w-40`, filters on symbol, tags and Thesis text, client side. `/` focuses it.
- **New idea**: `Button size="sm" className="h-7"`, `PlusIcon`. Key `N`.

### Idea list

A `Table` (primitives own type; no `text-*` overrides on cells). One row per Idea:

| Column | Content | Notes |
|---|---|---|
| Market | `TokenMark` + symbol in `font-sans`, Market name style as elsewhere | A 2 px left accent on the row: `--bid` when In zone, `--warn` when Past stop, none otherwise. |
| Side | `L` / `S` badge in bid / ask color | |
| Last | `price()` in `font-mono` | `—` when unknown (L1). |
| 24h | Daily Change, gain/loss colored | |
| To entry | **In zone** badge, or the signed % (L2) | A Watching Idea Past stop shows **Past stop** in `--warn` instead. Active shows **R now** (L5) as `+1.4R`. Closed/Dropped show the outcome. |
| R:R | The last Target's R multiple, one decimal | `—` without a complete Plan. Tooltip lists every Target's R. |
| Conviction | three dots, filled to 1–3 | |
| Tags | up to 2 chips, `+N` | |
| Next | the nearest future Catalyst as `in 3d` | Tooltip: its text and UTC date. Hidden under 1280 px wide. |
| Upd | relative time of `updated_at` | Tooltip: UTC time. |

Rows: click or Enter selects; `J`/`K` or ↓/↑ move; the selected row has the `bg-accent` the desk's tables use. Sorting by column heads reuses `SortableHeads` and `lib/tableSort.ts`. Header sort and column sort are the same state.

Empty states (`ui/empty`, no type overrides):
- No Ideas at all: title "No Ideas yet", description "An Idea is a Market, why you want it, and where you'd be wrong.", button **New idea**.
- Filter empty: "Nothing Watching." with a link to All.
- Search empty: "No Idea matches 'xyz'."

### Detail: header

- `TokenMark`, symbol (`text-lg`), side badge, status badge, conviction dots (clickable 1–3, saves at once), horizon (`Select`: Scalp, Swing, Position).
- One line under it: the first line of the Thesis, clamped to two lines, muted.
- Actions, right:
  - **Draft on chart** (primary, `variant="default"`): disabled with a tooltip "Needs an entry and a stop" until the Plan is complete (P6). Key `D`.
  - Status buttons, only the moves S2 allows: **Mark active**, **Close**, **Drop**, **Reopen**. Close and Drop open the Review dialog (S5) with outcome preselected (Close → Worked, Drop → Wrong) and a **Skip** button.
  - Overflow `⋯`: Open on desk (switches the desk's Market only, via the same channel, no Draft), Copy as text (Markdown of the Idea for a chat or a note), Delete (confirm dialog: "Delete ZRO long and its 12 log lines? This cannot be undone.").

### Detail: zone bar (`IdeaZoneBar`)

One SVG row, full width, 56 px tall, theme tokens only, readable in both themes:

```
  stop            entry zone        Last        T1          T2        T3
   ┃──────────────█████████─────────▲───────────┃───────────┃─────────┃
 2.0854        2.18 – 2.20        2.214       2.40        2.51      2.72
 −4.9%          In zone                       +1.9R       +3.0R     +5.0R
```

- The axis spans stop to the farthest Target, padded 6%, extended to include Last if Last is outside. Short Ideas draw the same left-to-right in price order; the labels say which side is which.
- Stop line `--ask`, zone band `--bid` at 25% opacity (short: `--ask`), Targets `--bid` ticks, Last a caret in `--foreground`, labelled.
- Under each mark: price, then the % from Last (stop, zone) or the R multiple (Targets).
- Without a complete Plan: a muted line "No Plan yet. Add an entry and a stop." that opens the Plan tab.
- Pure geometry lives in `lib/ideas.ts` (`zoneBarMarks(idea, last, width)`) and is unit-tested; the component only draws.

### Detail: mini chart (`IdeaChart`)

- `lightweight-charts`, candles from `GET /api/candles/{symbol}?resolution=4h&count=150`, Timeframe toggle **1h · 4h · 1d** (default 4h, remembered per page in `localStorage` through `storedFlag`/`storedList` helpers, wrapped in try/catch as they are).
- Plan lines as price lines, not draggable, labelled `ZONE`, `STOP`, `T1…`: same colors as the zone bar. The zone is two lines, `ZONE` on the high one. `chartPrimitive.ts` has no band; a shaded band is a later nicety, not v1.
- Options from `lib/chartOptions.ts`, fonts from `theme.fontMono` / `theme.chartFontSize`. Height 220 px. No crosshair readout beyond the default.
- Reload candles when the Timeframe or the Idea changes, not on the 10 s tick; update the last bar from Last on the tick.
- Clicking **Open on desk** under the chart does what the overflow item does.

### Detail: tabs

`Tabs` with **Thesis** (default) · **Plan** · **Log N** · **Trades N** · **Review** (Review only for Closed/Dropped).

**Thesis** — autosaves; each field saves on blur and on `⌘↵`, with a quiet "Saved" / "Not saved, retry" line under the form.
- **Why** — `Textarea`, 6 rows, grows to 16, placeholder "Why should this work? What is the market missing?". Required (I2): an empty save is refused inline, the old text stays.
- **Narratives** — tag chips with an input; Enter or comma adds; suggestions are every tag already used, most-used first; Backspace on an empty input removes the last chip (I4).
- **Catalysts** — rows of `[date (UTC)] [text] [×]`, **Add catalyst**. A date in the past is muted; within 7 days shows `in 3d` in `--warn`.
- **Invalidation** — `Textarea`, 3 rows, placeholder "What would prove this wrong, besides the stop?".

**Plan** — an explicit form with **Save** and **Cancel**, because each save writes a log line (S4).
- Entry: `ToggleGroup` **Zone** / **Price**. Zone shows Low and High inputs; Price one input (stored as low = high).
- Stop: one input. Its % from the plan entry is shown beside it, and **R** in price and %.
- Targets: up to four rows `[T1] [price | R toggle] [value] [% of Position] [×]`, **Add target**. Typing an R shows its price beside it, and the reverse (P4). The %s show their sum; above 100 it is an inline error (P5).
- Trigger: `Input`, placeholder "What must happen before entering? e.g. 4h close above 2.30".
- Summary line under the form, `font-mono`: `R 0.1054 (4.8%) · T1 1.9R · T2 3.0R · T3 5.0R · blended 3.1R` (blended = Σ R × % / Σ %, with the remainder at 0R when the %s are under 100; say so in the tooltip).
- Errors from P2 sit under the field that breaks them, with the server's sentence. **Save** is disabled while any field is invalid.
- **Use Last**: a small button beside Low/High/Price fills Last at the Market's `price_decimals`.
- Inputs reuse `CellInput` / `HeaderNumberInput` behaviour where it fits (decimal keyboard, tick snapping with `snapTick`).

**Log** — newest first.
- Composer at the top: `Textarea` 2 rows, placeholder "What changed?", **Add** (`⌘↵`).
- Each line: UTC time (`utcTime.ts`, "Oct 22 14:05 UTC"), Last at that time in `font-mono`, kind icon (✎ update, ⇢ plan, ● status, ▶ planner), body. Planner lines link the algo id to the desk's algo row if the desk can be told to open it; otherwise plain text.
- No edit, no delete of single lines (append only).

**Trades** — the Round trips D5 picks, from `api.journalTrips({ market, since: created_at, until: closed_at })`.
- Table: opened (UTC), side, size, entry, exit, Net (gain/loss color), R (Planner Round trips only; `—` otherwise).
- Footer: total Net, count, and **Open in Journal** (a plain link to `/journal`; the Journal keeps its Market filter in state, not the URL).
- Empty: "No Round trips on ZRO since this Idea was made."

**Review** — outcome `ToggleGroup` (Worked, Failed, Missed, Wrong), text "What did this teach you?", autosaves like Thesis. Above it, read-only facts: days open (created to closed), and the Trades total Net and R. Whether price reached T1 or the stop while the Idea was open is not shown in v1.

### New idea dialog (`NewIdeaDialog`)

`Dialog`, title "New idea", one column, `max-w-[480px]`:

1. **Market** — `Combobox` over `/api/markets` symbols with `TokenMark`, perps first (CONTEXT: the desk prefers the perp). Prefilled from `?symbol=` when opened from the desk (below).
2. **Side** — `ToggleGroup` Long / Short, Long default.
3. **Why** — `Textarea`, required, min 10 characters (I2), counter shows when under.
4. **Narratives** — tag input, optional.
5. **Plan** — collapsed `<details>` "Add a plan now (optional)": Zone/Price, Stop, one Target. Same validation as the Plan tab.
6. Footer: **Cancel**, **Create** (`⌘↵`). Create stays disabled until Market, Side and Why are valid.

After Create: the Idea is selected; if the server returned the I3 warning, a toast says "You already have an open ZRO long: TIA-… " with **Show** that selects it.

### Keyboard

`N` new · `/` search · `J`/`K` next/previous · `Enter` focus detail · `D` Draft on chart · `E` Plan tab in edit · `L` Log composer · `Esc` closes dialogs, then clears search. Ignore keys while an input has focus (reuse `lib/keyTarget.ts`). List them in a `?` popover on the header with `Kbd`.

### Type and color

- Type tokens only (`text-xs`…`text-lg`), as `.cursor/rules/typography.mdc`; prices, %, R in `font-mono`; names and prose in `font-sans`. No `text-[Npx]`.
- Long/short use `--bid`/`--ask`; gain/loss reuse the Journal's colors; In zone `--bid` accent; Past stop and near Catalysts `--warn`. No new colors.
- Every time on the page is UTC and says so, as on the Portfolio (W2).

### Draft hand-off (desk side)

1. `lib/deskBridge.ts`: add to `DeskMessage` and `isDeskMessage`:
   - `{ type: "desk-ping" }` and `{ type: "desk-pong" }`;
   - `{ type: "idea-draft"; symbol: string; ideaId: string; draft: ChartDraft }` (validate numbers > 0, targets an array of `{r, pct}` strings).
   - `{ type: "desk-symbol"; symbol: string }` for Open on desk. Do **not** reuse `"symbol"`: the Watch window already listens to it.
2. A new `useDeskIdeasBridge({ onSymbol })` in the Dashboard (next to `useDeskWatchBridge`): answers `desk-ping`, and on `idea-draft` calls `onSymbol(symbol)`, `setChartDraft(symbol, draft)` with the idea id, toasts "Draft replaced with the ZRO Idea's plan" when a Draft was there, then `requestChartDraftOpen()`. The Planner dialog opens on the desk tab; the browser will not focus that tab by itself, so the Ideas page shows a toast "Draft sent to the desk tab".
3. `lib/ideas.ts` `ideaToDraft`: entry = plan entry (P3), stop, targets as R multiples from P3 with their %s, or `defaultDraftTargets()` when the Idea has none (P5).
4. D2 fallback: no pong in 500 ms → `window.open("/" + symbol + "?idea=" + id, "_blank")`. The Dashboard reads `?idea=` once on load, fetches `GET /api/ideas/{id}`, builds the Draft the same way, opens the dialog, then strips the query with `replaceState`.
5. D4: the Planner dialog's start path (`PlannerDialog.tsx`) reads `draftIdea(symbol)`; when set and the start answers with an algo id, call `api.ideaPlanner(ideaId, algoId)` and clear the link. A failure toasts and does not touch the Planner.

### From the desk into Ideas (small, step 5)

- The **Ideas** header button.
- Market picker: a small `Lightbulb` mark beside Markets with an open Idea (one `GET /api/ideas?status=open` on load and every 60 s; symbols only). Clicking the mark opens `/ideas?symbol=ZRO` (selects that Idea, or opens New idea prefilled).
- Chart: an **Ideas** toggle in the chart's overlay menu draws the open Idea's zone, stop and Targets on the price chart as faint, non-interactive lines labelled `IDEA` ([ADR 0007](../adr/0007-chart-amends-tickets-only.md): display only). Off by default. A new `ChartOverlay` kind `"idea"`, never `interactive`.
- Draft → Idea: when a Draft exists, the Planner dialog gets a quiet **Save as Idea** link that opens `/ideas?symbol=…&entry=…&stop=…&t=…` with New idea prefilled. The Thesis is still required there.

---

## 7. Out of scope (v1)

- Any order from the Ideas page, or price-triggered entries (ADR 0020).
- A Push or toast when an Idea goes In zone or Past stop. If wanted later, it is a new row in [push-rules.md](../push-rules.md) first, keyed `idea:{id}:zone`, once per entry into the zone, and it states the fact only ([ADR 0013](../adr/0013-an-alert-is-a-fact-and-a-toast-is-a-coincidence.md)). It would need the backend to watch Last, so it waits for its own decision.
- Rich text, images or links previews in the Thesis. Plain text; URLs become links on display only.
- Sizing on the page. The Planner sizes from risk.
- Sharing or more than one viewer (CLAUDE.md).
- Markets not on Lighter.
- Backfilling Ideas from the Journal's notes.

---

## 8. Tests

Backend (`unittest`, like the rest):
- `test_ideas.py` (pure): every rule I1–I6, P1–P6, S2, S4's diff text, S5 outcomes.
- `test_ideas_api.py`: create/list/get/patch/status/review/log/planner/delete shapes; 422 text for each Refusal; 409 for a bad status move; a Plan change and a status move each write exactly one log line with Last from a faked gateway; D4 idempotent per algo id; S6 removes the log. Use the in-memory DB setup `test_journal_api.py` uses.
- `test_migrations.py`: step 16 from 15, and a fresh file.
- `test_api_contract.py` / `test_api_types.py`: pass after `make api-types`.

Web (`vitest`, jsdom):
- `lib/__tests__/ideas.test.ts`: L1–L5 on long and short, single price and zone; D5 window; P4 both ways at a Market's decimals; `ideaToDraft`; `zoneBarMarks` order and padding; blended R.
- `lib/__tests__/deskBridge.test.ts`: the new messages pass `isDeskMessage`; a malformed `idea-draft` does not.
- `lib/__tests__/chartDraft.test.ts`: `setChartDraft` replaces, links the idea id, and `clearChartDraft` clears the link.
- `components/__tests__/IdeasPage.test.tsx` with fixtures: empty state; list sorts by Nearest entry; In zone and Past stop accents; New idea refuses an empty Why; Plan form shows R and refuses a stop above a long zone; Draft on chart pings, and opens a desk tab when no pong comes (mock `window.open`, fake timers); the page never opens a WebSocket (spy on `WebSocket`).
- `components/__tests__/PageNav.test.tsx`: Ideas is listed and is the title on `/ideas`.
- `test_browser_guard.py`: a foreign Origin cannot write an Idea.

Never use the live desk to test D3/D4. Planner start is covered by mocks on the web side and `planner_harness.py` on the backend side.

---

## 9. Order

Each step is one commit to `main` with `make ci` green, and the rules doc changed in the same commit as the code it describes.

| Step | What | Size |
|---|---|---|
| 1 | CONTEXT.md words (§1), `docs/idea-rules.md` (§3), ADR 0020. Settle §0 first. | S |
| 2 | Migration 16, `ideas.py`, `persist_ideas.py`, routes, schemas, `make api-types`, backend tests. | M |
| 3 | `/ideas` route, nav, header button, `lib/ideas.ts`, list + New idea + Thesis tab + Log tab, page tests. | L |
| 4 | Plan tab, zone bar, mini chart, Trades and Review tabs. | M |
| 5 | Draft hand-off (bridge messages, `setChartDraft`, `?idea=` fallback, D4 on Planner start). | M |
| 6 | Desk extras: picker mark, chart Ideas overlay, Save as Idea from the Planner dialog. | M |

Steps 3 and 4 touch the same page; do them in order. Step 5 can start once step 2 is in, in parallel with 3–4, because it only touches `deskBridge.ts`, `chartDraft.ts`, `Dashboard.tsx` and `PlannerDialog.tsx` (the Ideas page's button lands with step 4 or 5, whichever is second).

When step 6 ships, add a screenshot `docs/screens/ideas.png` and a line in the README's screens list if it has one.

---

## 10. Risks

- **The word.** Shipping "Watchlist" for both things. §0 decides it first.
- **Two desk tabs.** The fallback in D2 must only open a tab when no desk answered. Test the timeout. If a second desk tab ever opens, both would hold Drafts and the operator could start a Planner from the wrong one.
- **A stale Draft.** The Idea's Plan can change after the Draft was sent. The Draft is a copy at send time; the desk does not follow later edits. Say so in the toast ("Draft from the plan as of 14:05").
- **A zone is not an order type.** The plan entry is the midpoint (P3). A Planner Ladder entry over the zone is the natural fit but needs the Draft to carry from/to; leave it for later and say so in the rules doc.
- **Price precision.** Prices are typed strings; convert with the Market's `price_decimals` only when computing, never when storing (I6).
- **Unlisted Markets.** Lighter delists. I1 keeps the Idea; the page must not crash on a missing Market or price.
- **Autosave races.** Two quick blurs can land out of order. Send each field's save with the `updated_at` the page last saw and let the server refuse an older one with 409; the page reloads that Idea and shows "Changed elsewhere, reloaded".
