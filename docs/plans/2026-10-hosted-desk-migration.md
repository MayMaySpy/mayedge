# Hosted desk migration plan — late October 2026

The desk today is one Python process that holds one Lighter API key and serves one browser tab. This plan turns it into a **hosted desk**: a TypeScript server on the VPS that anyone can open in a browser, connect their own Lighter account to, and trade from. The server never holds a trading key. Each browser signs its own orders with Lighter's WASM signer.

The desk stays the same desk. Chart, Scan, Watch, Alerts, Pushes, Tickets, Kill, Auto kill, Positions, Journal, Portfolio and Ideas all keep their rules, their words and their screens. **Algos are out of scope** (Chase, Grid, Ladder, TWAP the algo, Planner, Trail). They come back later as their own plan (section 8). Venue-native TWAP, the order type, stays.

The one algo in v1 is the **Rebalancer**, because it never needs a tab open between runs. It trades **Baskets**: weighted sets of coins, long, short or spot, each in a sub-account of its own. Baskets are the hosted desk's first product. Their scope is [2026-10-basket-scope.md](2026-10-basket-scope.md); this plan says where they fit (section B).

The web app is already TypeScript (35k lines). What gets rewritten is the backend: 33k lines of Python, of which 11k are algos. About **22k lines of Python** move, together with the 20k lines of tests that pin them.

| # | Work | Kind | Size |
|---|---|---|---|
| 0 | Prove the venue in a browser (spikes) | Probe | S (1 wk) |
| 1 | Workspace and the `core` package | Port | L (3–4 wk) |
| 2 | Market server | Port | L (3–4 wk) |
| ⏸ 1 | Shadow run next to the Python desk | Checkpoint | 1 wk |
| 3 | Sign-in and per-user data | Feature | L (3 wk) |
| 4 | Trading from the browser | Feature | L (3–4 wk) |
| 5 | The browser reads its own market | Port | M (1–2 wk) |
| B1 | Paper Baskets and Backtests (after 3) | Feature | M (2–3 wk) |
| B2 | Live Baskets and the Rebalancer (after 4) | Feature | L (3–4 wk) |
| ⏸ 2 | Testnet beta | Checkpoint | 1–2 wk |
| 6 | Hardening and launch | Upkeep | M (2 wk) |
| 7 | Rate limits, all in one place | Reference | — |
| 8 | Later: algos in the tab | Feature | — |

Sizes are for one developer who knows TypeScript and has read this repo. They are rough. Total: about 23 to 31 weeks with Baskets.

---

## What the review found

From the code on 2026-10-29 and Lighter's developer docs as read that day.

| Finding | Evidence |
|---|---|
| One process holds the only trading key | `lighter_api_private_key` in `backend/src/mayedge/config.py`; `SignerClient` in `lighter/orders.py` |
| No login, on purpose | [ADR 0005](../adr/0005-no-app-auth-loopback-tailscale.md): loopback plus Tailscale. Anyone who reaches the port can trade |
| One WebSocket carries everything | `web/src/hooks/useMarketWs.ts` handles market (`order_book`, `trades`, `candle`, `market_stats`), market-wide (`alerts`, `scan_activity`, `tone_board`, `liquidations`, `funding_extremes`) and account (`account`, `account_trades`, `algo`, `auto_kill`, `budget`, `journal_open`) messages on `/ws` |
| The server follows the tab's market | `market_switch` and `POST /api/markets/{symbol}/activate` move the server's own `order_book` and `trade` subscriptions (`lighter/market_ws.py`) |
| One budget for everything | `lighter/budget.py`: 54 requests and 38 sends a rolling minute, algos held to 30, Kill never refused |
| Money math is `Decimal` | 43 backend files import `Decimal` |
| Tones run in a process pool | `tone_compute.py` uses `ProcessPoolExecutor` |
| SQLite holds market history and personal records in one file | `db.py`, `migrations.py`: market tables (`liquidations`, `oi_*`, `funding_*`, `alert_*`) next to personal ones (`journal_*`, `portfolio_pnl`, `ideas`, `idea_log`, `idea_alerts`, `algo_*`) |
| Favorites, mutes and layout already live in the browser | `web/src/lib/storedList.ts`, `storedFlag.ts`: `localStorage` |
| Lighter's WASM signer runs in a browser | [WASM signer](https://docs.lighter.xyz/developers/reference/wasm-signer.md): `GenerateAPIKey`, `SignChangePubKey`, `SignCreateOrder`, `SignCancelOrder`, `CreateAuthToken`. It cannot open network connections; JavaScript does every `fetch` |
| Lighter says: a key per user, made on their device | [TypeScript quickstart](https://docs.lighter.xyz/developers/getting-started/quickstart-typescript): never ship your own key to a browser; generate one per user and register it through their wallet |
| A read-only token exists | [API keys](https://docs.lighter.xyz/developers/integration-guides/api-keys.md): `ro:{account}:{single\|all}:{expiry}:{hex}`, 5 minutes to 10 years, `read.*` only, cannot trade, withdraw or start a signer. Creating one costs 10,000 request weight |
| Rate limits are keyed by IP and by wallet | [Rate limits](https://docs.lighter.xyz/developers/reference/rate-limits.md): REST counts per IP **and** per L1 address; an authenticated request drops the IP limit. `sendTx` counts per L1 address only. WebSocket counts per IP, including a cap on unique accounts |
| `lighter-ts` is not a signer | [SDKs](https://docs.lighter.xyz/developers/getting-started/sdks): a state store, WebSocket pipeline and trading math; "pair it with the WASM signer" |
| Lighter has no login SDK | The closest pieces are the auth token (≤ 8 hours, from the API key) and the read-only token. Identity has to come from the wallet |

---

## The target shape

```
                ┌───────────────────────────── VPS ─────────────────────────────┐
                │  Caddy (TLS, static web, CSP)                                  │
                │      │                                                         │
                │  Market server (Node 22, TypeScript)                           │
                │   ├─ market feed   one Lighter WS + public REST, one budget    │
                │   ├─ Scan, Alerts, Tones, OI, Funding, Liquidations, Backups   │
                │   ├─ per-user area  sign-in, Journal, Portfolio, Ideas,        │
                │   │                 Idea alerts, Pushes  (read-only tokens)    │
                │   └─ SQLite         market tables + per-user tables            │
                └───────────────▲──────────────────────────▲─────────────────────┘
                     /ws, /api  │                          │ REST with read-only token
                                │                          │ (counts on the user's wallet)
        ┌─────── user's browser ┴─────────┐                │
        │  web app (same React desk)      │                │
        │  venue module:                  │   sendTx, account WS, own market WS
        │   WASM signer in a Worker  ─────┼──────────────► Lighter ◄─────┘
        │   key vault (IndexedDB)         │
        │   account feed, orders, Kill,   │
        │   Auto kill, Send budget        │
        └─────────────────────────────────┘
```

Who does what:

| Piece | Runs in | Lighter identity it uses | Why there |
|---|---|---|---|
| Market feed, Scan, Alerts, Tones, OI, Funding, Liquidations, Backups, Heartbeat | Market server | none (public) | Must run with no tab open; same answer for every user, so compute once |
| Sign-in, sessions | Market server | the user's wallet signature | Lighter has no login |
| Journal sync, Portfolio sync, Positions poll for Pushes, Idea alert watch | Market server, per user | the user's read-only token | Must run with no tab open; cannot trade |
| Telegram Pushes and `/status` | Market server, per user | none | One bot, each user links their own chat |
| Key, signer, nonces | Browser (Worker) | the user's API key | The server must never be able to trade |
| Account feed (positions, orders, trades, assets) | Browser | auth token from the API key | WebSocket limits count per IP and per unique account; the server cannot hold everyone's account feed |
| Tickets, Amend, cancel, leverage, SL/TP, venue TWAP | Browser | API key | Signed where the key is |
| Kill | Browser | API key | Same |
| Auto kill | Browser, **tab-bound** | API key | No server key exists to flatten with |
| The chart's own market (book, trades, candles) | Browser (from section 5) | none | Each user's IP has its own limits; the server's do not grow with users |

---

## Decisions

Each one becomes an ADR in the commit that first depends on it (Ground rules, rule 6).

**D1. The server never signs.** No API private key exists on the VPS, in `.env` or anywhere else. A server bug, a leaked backup or a stolen VPS cannot place an order. This is the line the whole plan is built on.

**D2. Sign in with the wallet that owns the Lighter account.** Sign-In with Ethereum (EIP-4361) gives the server an L1 address it has verified. Lighter's `accountsByL1Address` maps that address to Account indexes. No password, no email, no second identity. This replaces ADR 0005 for the hosted desk; the local desk keeps 0005 until it is retired.

**D3. The server reads a user's account only with a read-only token.** The browser makes one after the key is registered and hands it to the server. The server stores it encrypted and uses it for Journal, Portfolio and the Positions poll. A leaked token shows a user's account; it cannot move it.

**D4. One tab drives one key.** Web Locks (`navigator.locks`) give the signer to the first tab. A second tab opens read-only and says so. This keeps one nonce stream per key and keeps the desk single-viewer per user.

**D5. Auto kill and every live order rule are tab-bound, and the desk says so.** Closing, sleeping or losing the tab stops Auto kill. The Kill menu, the Auto kill badge and the sign-up screen say it in one sentence. When a tab with Auto kill armed disconnects, the server sends a Push saying Auto kill stopped watching. Venue stops still hold, which is what Positions-row Stop and Take Profit are for.

**D6. Same contract, new language.** The market server keeps every HTTP path and every WebSocket message type the web app uses today, with the same JSON. The web app changes where it must (sign-in, the venue module) and nowhere else. This is what makes the shadow run (checkpoint 1) possible.

**D7. A `core` package holds every rule that is not I/O.** Parsing, error classes, the Send budget, numbers, MayRekt, Tones, alert rules, Journal building, Portfolio math, Push texts and Idea checks are pure functions in `packages/core`. Both the server and the browser import them. One copy of each rule, one set of tests.

**D8. `lighter-ts` is a reference, not a dependency.** It is built on Zustand and React Query; the desk is not. Its value is showing how Lighter's frontend reads the feed. The desk ports its own `lighter/parse.py`, which its tests already pin.

**D9. `Decimal` stays `Decimal`.** Every place the Python uses `Decimal`, TypeScript uses `decimal.js` (pinned). A JavaScript `number` never holds a price, a size or money. Venue integers (scaled prices and sizes, order indexes) are `bigint` or decimal strings, never `number`.

**D10. SQLite stays.** `better-sqlite3` with WAL, the same tables, the same migrations continued. Per-user tables gain a `user_id`. One VPS, one file, the same Backups. Postgres is not needed at this size and would cost the data migration.

**D11. The server's public budget does not grow with users.** Every public read the server makes is market-wide, on a timer or a cache with bounded keys. No user request can make the server spend public requests per user. This is an invariant with a test (section 2.9).

**D12. Testnet for every signed transaction until launch.** The local desk at `:14200` is live mainnet and stays untouched. The hosted desk signs on testnet (chain id 300) with a throwaway wallet until checkpoint 2 is passed. The first mainnet order is placed by the owner, by hand.

---

## What changes for a user, compared with today's desk

| Area | Today | Hosted v1 |
|---|---|---|
| Chart, Pinned timeframes, MayRekt, OI and Fund panes, Axis, Fills | Same | Same |
| Scan (Strength, Liquidation heat, Activity, Tones board) | Same | Same; Tone timeframes picked per user from the set the server computes (section 3.8) |
| Watch, popout | Same | Same |
| Alerts, Left and Against, Opened, 24h record, what-if, Funding strip | Same | Same facts for everyone; Opened is per user; Held market and Near liquidation come from the user's own account |
| Pushes | One Telegram chat from `.env` | Each user links their own chat; same events and texts |
| Tickets: market, limit, Notional, Quick size, venue TWAP, Stop and Take Profit, Amend, Bids and Asks cancel, cancel all, leverage | Signed by the server | Signed by the browser |
| Kill | Server | Browser |
| Auto kill | Server, always on | Browser, tab-bound (D5) |
| Positions, Assets, Orders, History | Server feed | Browser feed |
| Algos tab, Clips, Planner and Trail lines | Live | Hidden |
| Journal, Excursion, `/journal` | Server, one account | Server, per user, read-only token |
| Portfolio, Today, `/portfolio` | Server, one account | Server, per user, read-only token |
| Ideas, Idea log, Price alerts, Draft on chart | Server | Server, per user |
| Idea **Start** (Planner) | Live | Off until algos return; the button says why |
| Send budget readout | The server's budget | The browser's budget for that account |
| Feed status | Desk feeds | Market server feed, plus the browser's own account and market feeds |
| When the desk was not watching | Server boot and Freeze pushes | Same for the server; the tab reports its own sleep (section 4.10) |
| Baskets, Paper Baskets, Backtests, the Rebalancer | Do not exist | New (section B) |

---

## Ground rules (read before any section)

1. **Read first:** [README.md](../../README.md), [CONTEXT.md](../../CONTEXT.md), [lighter-limits.md](../lighter-limits.md), the rules doc of the area you port (`docs/*-rules.md`) and the ADRs. Words in bold mean what CONTEXT.md says. New words in this plan (hosted desk, market server, venue module, key vault, read-only token) go into CONTEXT.md in the first commit that uses them, with an `_Avoid_:` line.
2. **The rules docs are the spec.** A ported module behaves as its rules doc says. Where the Python and the doc disagree, stop and ask; do not pick one quietly.
3. **Port the tests first.** For each Python module: translate its `backend/tests/test_*.py` to Vitest, watch it fail, port the code, watch it pass. A module is not ported while a test of it is missing. Where a Python test drives a fake (`venue_harness.py`, `chase_harness.py`, `planner_harness.py`), port the fake into `packages/core/test/fakes`.
4. **Parity fixtures.** `backend/scripts/dump_parity.py` runs the Python on recorded inputs and writes the outputs as JSON into `packages/core/test/parity/`. The TypeScript must produce the same JSON. Record the inputs from public mainnet data (candles, trades, `market_stats`); never from an account.
5. **Never sign on mainnet.** See D12. CLAUDE.md's rule holds: no order is placed, amended or cancelled on the live desk to test anything.
6. **Rules before code** ([ADR 0011](../adr/0011-alert-rules-are-written-down-before-they-are-coded.md)). A changed behaviour lands in one commit: the doc, the code and its pinning test. The decisions above land as ADRs 0023 and up in the commit that first relies on them.
7. **Commits:** straight to main, one plain sentence each, `make ci` green first (`.cursor/rules/commit.mdc`). Section 1 extends `make ci` to the new packages.
8. **The Python desk keeps running.** Nothing in `backend/` is deleted until section 6.8.

---

## 0. Prove the venue in a browser

Every item is tried on **testnet** with a fresh wallet that holds nothing else. Results go into `docs/plans/2026-11-hosted-desk-spikes.md`, one row each: what was tried, what came back, pass or fail. The spike code lives in `spikes/` and is thrown away.

| # | Question | How to try it | Pass | If it fails |
|---|---|---|---|---|
| S1 | Does Lighter's REST answer a browser on our origin? | From a Vite page on `http://localhost:5173` and from a throwaway `https://*.pages.dev` page, `fetch` `orderBookDetails`, `candles`, `nextNonce`, `accountLimits` (with auth), `sendTx` | No CORS error; responses read | **Relay** (below) |
| S2 | Does Lighter's WebSocket accept our Origin? | Open `wss://testnet.zklighter.elliot.ai/stream` from both pages; subscribe `order_book/0`, then `account_all_orders/{account}` with an auth token | Both stream | Relay for public channels; account feed relay is not possible at scale (D11), so this is a stop-and-decide |
| S3 | Can the browser build and load the signer? | Build `lighter-go/wasm` at the commit matching `lighter-sdk` 1.1.8; same Go version for `wasm_exec.js`; serve as `application/wasm`; `instantiateStreaming` in a Worker | `GenerateAPIKey` returns a pair | Pin a different lighter-go tag and retry |
| S4 | Can a browser wallet register the key? | `SignChangePubKey` → find what the L1 wallet must sign → `personal_sign` in MetaMask and Rabby → `sendTx` | `accountLimits` with an auth token from the new key returns 200 | Read `lighter-python`'s `change_api_key` and the "create accounts programmatically" guide for the exact message |
| S5 | Does the WASM signer do every transaction the desk sends? | For each row of the transaction list below, sign and send on testnet | Every one is accepted and shows on the account feed | List what is missing; a missing one is either dropped from v1 or blocks it |
| S6 | What does a read-only token see? | Create one (`tokens/create`, scope single account); call `account`, `accountActiveOrders`, `trades`, `pnl`, `positionFunding`, `accountLimits`; subscribe the account channels with it | Every one the server needs answers | The server falls back to an 8-hour auth token the tab refreshes; Journal stops syncing when no tab has been open for 8 hours |
| S7 | Whose budget does a read-only request spend? | Spend 60 requests in a minute with the token from one IP; then from a second IP with the same token | The limit follows the wallet, not the IP | Recompute the budget table (section 7) |
| S8 | What can an API key sign beyond trading? | Read the signer's exports and Lighter's docs for withdraw and transfer; try `SignWithdraw` on testnet | Written answer: what a stolen key can do | Drives the key vault strength and the sign-up warning |
| S9 | How is a key revoked? | Replace the key at the same index with a fresh one; check the old one is refused | Old key refused | Document the venue's own revoke path |
| S10 | Does the WAF treat browser traffic differently? | Watch for `x-amzn-waf-action` and 405 during S1–S7 | Never seen | Note the trigger; Send budget lanes stay conservative |
| S11 | Can the browser create a sub-account and register a key on it? | Create a sub-account under the test account from the tab; generate a key; ChangePubKey on the sub-account's index; note whether the main key or the L1 wallet signs each step | `accountLimits` on the sub-account answers 200 with the new key | Basket scope section 16: one live Basket on the main account |
| S12 | Does the WASM signer sign spot orders? | Market and limit orders on a testnet spot Market | Accepted; the asset shows in `account_all_assets` | Spot Parts wait; Baskets ship perps only |
| S13 | Do spot assets count as perp collateral? | Hold a spot asset in a sub-account and open a perp; read `accountLimits` and margin | Written answer | Basket rule Z2 keeps spot fully paid and not collateral |
| S14 | Can the browser move money between the user's own accounts, and does an `all` read-only token cover sub-accounts? | Transfer USDC main → sub → main; read the sub-account with the main account's `all` token | Both work | A read-only token per sub-account (10,000 weight each) |

Transactions the desk sends today (from `lighter/orders.py`), all of which S5 tries:

| Desk action | Venue transaction |
|---|---|
| Market Ticket, Kill flatten, floating Buy/Sell | create order, type Market (1), IOC |
| Limit Ticket, Axis rest | create order, type Limit (0), GTT or Post-only, 28-day expiry |
| Venue TWAP | create order, type TWAP (6) |
| Positions-row Stop and Take Profit | grouped create order (OCO), types 2–5 |
| Amend | modify order |
| Cancel one | cancel order |
| Bids, Asks | cancel order, one per Ticket |
| Cancel all, Kill | cancel all orders, immediate, `NIL_MARKET_INDEX` (255) or one market |
| Leverage | update leverage |

**Relay** is the fallback for S1: the browser signs, then posts the signed transaction to `POST /api/relay/sendTx` on the market server, which forwards it unchanged. The server sees a signed transaction, never a key, so D1 holds. `sendTx` counts per wallet, not per IP, so the relay does not spend the server's budget. Reads would then have to come through the server's caches (section 2.6), which caps the number of users. Write the cap down if this path is taken.

**Exit:** S1–S6 pass, S11–S14 are answered before section B2, or each failure has its fallback written into this plan. Get the owner's go before section 1.

---

## 1. Workspace and the `core` package

### 1.1 Layout

```
package.json            npm workspaces: packages/*, server, web
packages/core/          pure TypeScript, no I/O, no Node or DOM APIs
packages/core/test/     Vitest, fakes/, parity/
server/                 Node 22 market server
web/                    the existing desk (unchanged layout)
backend/                the Python desk, until section 6.8
```

- TypeScript 6, `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`. The same oxlint config as `web/`.
- `packages/core` builds with `tsc` to ESM. `web` and `server` import it by workspace name `@mayedge/core`.
- `make ci` gains `ci-core` and `ci-server` (oxlint, `tsc --noEmit`, Vitest). `.github/workflows/ci.yml` follows.

### 1.2 Libraries

| Need | Library | Note |
|---|---|---|
| Decimal math | `decimal.js` | D9. One `Dec` helper in `core/numbers.ts` mirrors `numbers.py` |
| Schemas, request checks | `zod` | Replaces pydantic. Response types are exported from `core/api` and imported by `web` |
| Server | `fastify` 5, `@fastify/websocket`, `@fastify/cookie` | |
| SQLite | `better-sqlite3` | Synchronous: see 2.2 |
| YAML (`alerts.yaml`) | `yaml` | |
| Worker pool (Tones) | `piscina` | Replaces `ProcessPoolExecutor` |
| Wallet, SIWE | `viem` | `verifySiweMessage`, `personal_sign` |
| Telegram | plain `fetch` | Same as the Python, no SDK |

Pin exact versions. No `^`.

### 1.3 What goes into `core`, in order

Port in this order; each line is one or more commits, tests first (rule 3).

| Order | Python | `core` module | Tests to port |
|---|---|---|---|
| 1 | `numbers.py` | `numbers.ts` | `test_numbers.py` |
| 2 | `lighter/models.py`, `lighter/channels.py`, `lighter/parse.py` | `venue/models.ts`, `venue/channels.ts`, `venue/parse.ts` | `test_market_type.py`, `test_trade_channel.py`, `test_account_merge.py`, `test_account_assets.py`, `test_rows.py` |
| 3 | `lighter/errors.py` | `venue/errors.ts` | `test_venue_errors.py` (every row of the errors table in lighter-limits.md) |
| 4 | `lighter/budget.py` | `venue/budget.ts` (clock injected) | `test_lighter_budget.py` |
| 5 | `lighter/coi.py`, `lighter/fees.py`, `lighter/equity.py` | `venue/coi.ts`, `venue/fees.ts`, `venue/equity.ts` | their tests; COI keeps every band so algos fit later |
| 6 | order building and checks from `lighter/orders.py` (scaling, maker minimums, notional cap, worst price, trigger side, `reject_reason` use) | `venue/orderBuild.ts` | `test_market_order.py`, `test_sl_tp.py`, `test_twap_order.py`, `test_amend_ticket.py`, `test_cancel_tickets.py`, `test_liquidation_price.py` |
| 7 | `kill.py`, `auto_kill.py` | `kill.ts`, `autoKill.ts` (venue calls injected) | `test_kill.py`, `test_auto_kill.py` |
| 8 | `mayrekt.py`, `tone_timeframes.py`, tone math from `tone_compute.py` | `mayrekt.ts`, `tones.ts` | `test_mayrekt.py`, `test_tone_compute.py` + parity fixtures |
| 9 | `alerts.py`, `alert_rows.py`, `alert_settings.py`, `alert_stats.py`, `tone_alerts.py` (rules only) | `alerts/*.ts` | `test_alerts.py`, `test_alert_stats.py`, `test_tone_alerts.py` + parity fixtures of a recorded day |
| 10 | `journal.py`, `journal_build.py`, `journal_excursion.py` | `journal/*.ts` | `test_journal.py`, `test_journal_excursion.py` |
| 11 | `portfolio.py` | `portfolio.ts` | `test_portfolio.py` |
| 12 | `ideas.py`, `idea_alerts.py` (rules) | `ideas/*.ts` | `test_ideas.py`, `test_idea_alerts.py` |
| 13 | `push_text.py`, push rules from `push_router.py` | `push/*.ts` | `test_push.py` (texts and routing) |

### 1.4 Parity fixtures

1. Write `backend/scripts/dump_parity.py`. For each of MayRekt, Tones, alert rules, Journal build and Portfolio, it loads an input file, runs the Python, and writes `{input, output}` JSON.
2. Inputs: one recorded UTC day of public mainnet candles, trades and `market_stats` for 20 liquid perps (`backend/scripts/record_public_day.py`, read through the desk's own gateway so no new venue load is added), and the Journal's existing anonymised test fixtures.
3. A Vitest suite per module reads every fixture and compares. `Decimal` outputs compare as strings.

**Done when:** every ported Python test has a passing Vitest twin, parity suites pass, `make ci` runs all three packages.

---

## 2. Market server

Everything market-wide, with the same HTTP paths and WebSocket messages as today (D6). No account, no key.

### 2.1 Process

- `server/src/main.ts`: load config, open the database, run migrations, start the market feed, start timers, listen.
- Config from `server/.env` with zod: `LIGHTER_NETWORK`, `DB_PATH`, `ALERTS_CONFIG`, `BIND_HOST`, `BIND_PORT`, `PUBLIC_ORIGIN`, `SESSION_SECRET`, `TOKEN_KEY` (encrypts read-only tokens), `TELEGRAM_BOT_TOKEN`, `HEARTBEAT_URL`, `BACKUP_DIR`, `BACKUP_KEEP`, `BACKUP_AT`, `OWNER_L1_ADDRESS`. There is no `LIGHTER_API_PRIVATE_KEY` and the config refuses to boot if one is set (D1).
- Graceful stop on SIGTERM: stop timers, flush writes, close sockets, mark clean (`alive.py`).

### 2.2 Database

- Port `db.py` and `migrations.py` to `server/src/db/`. Keep the `meta` version row and continue its numbering; the TypeScript runs the same schema the Python left, so the owner's file opens unchanged (section 6.6).
- `better-sqlite3` is synchronous and blocks the event loop like the old in-loop reads did (reliability plan, section D). Any read measured over 20 ms on the owner's 632 MB file runs in a worker thread: the Journal summary and trips, OI history, the hourly OI fold, alert what-if. Write the measured times in the commit message.
- One writer. Batch inserts in transactions (OI samples, trades, liquidations) the way the persist modules do.

### 2.3 Lighter client

- `server/src/venue/rest.ts`: a typed `fetch` client for the public endpoints in lighter-limits.md's table. Every call goes through a `RestBudget` from `core` with the server's lanes (`read`, `background`). There is no `algo` lane and no Kill lane on the server.
- `server/src/venue/marketWs.ts`: port `lighter/market_ws.py` and `order_book.py`. One connection. Subscribes `market_stats/all`, the `trade/{i}` channels the alerts and liquidation feed need, and the 1m `candle/{i}` channels the minute alerts need. Reconnects the same way; 503 and close 1012 still say Lighter is down.
- Until section 5, the server also follows a **set** of markets for the tabs' charts: the union of every connected tab's market, capped (start at 12). Over the cap, a tab's book and trades come from the browser directly (section 5) or wait. Write the cap into `lighter-limits.md`.

### 2.4 Port the rest of the market side

| Python | Server module | Tests |
|---|---|---|
| `lighter/gateway.py`, `gateway_boards.py` | `market/gateway.ts`, `market/boards.ts` | `test_market_ws.py`, `test_order_book.py`, `test_scan_loop.py` |
| `lighter/liquidations.py`, `persist_liq.py` | `market/liquidations.ts`, `db/liq.ts` | `test_liquidations.py` |
| `persist_oi.py` | `db/oi.ts` | `test_open_interest.py` |
| `persist_funding.py`, `funding_backfill.py` | `db/funding.ts`, `market/fundingBackfill.ts` | `test_funding.py` |
| `tone_compute.py` | `market/tones.ts` on `piscina` | `test_tone_compute.py` |
| `alert_log.py`, alert engine side of `alerts.py` | `market/alerts.ts`, `db/alerts.ts` | `test_alert_log.py`, `test_alerts.py` |
| `feed_health.py`, `loop_watch.py`, `alive.py`, `heartbeat.py`, `backup.py` | `health/*.ts` | `test_loop_watch.py`, `test_alive.py`, `test_heartbeat.py`, `test_backup.py`, `test_venue_down.py` |
| `api/ws.py` (fan-out, replace types, bounded queue) | `http/ws.ts` | `test_ws_fanout.py`, `test_ws_send.py` |
| `api/guard.py` (Host and Origin) | `http/guard.ts` | `test_browser_guard.py` |
| `api/spa.py`, `api/token_icon.py` | Caddy serves the SPA; `http/tokenIcon.ts` | `test_spa.py` |

### 2.5 Routes kept on the market server

Same paths and JSON as today:

`GET /api/health`, `/api/markets`, `/api/markets/{symbol}`, `/api/candles/{symbol}`, `/api/oi/{symbol}`, `/api/funding/{symbol}`, `/api/funding/{symbol}/average`, `/api/liquidations`, `/api/liquidations/summary`, `/api/scan/activity`, `/api/scan/tones`, `/api/scan/tones/timeframes` (GET), `/api/alerts`, `/api/alerts/stats`, `/api/alerts/settings`, `/api/alerts/whatif`, `/api/alerts/funding`, `/api/token-icon/{slug}`; `POST /api/markets/{symbol}/activate` (adds the tab's market to the followed set).

WebSocket messages kept on `/ws`: `init`, `market_switch`, `order_book`, `order_book_snapshot`, `order_book_delta`, `trades`, `candles`, `candle`, `market_stats`, `liquidations`, `alerts`, `scan_activity`, `funding_extremes`, `tone_board`, `feed_health`, `book_sync`, `desk_freeze`.

### 2.6 Caches

- `/api/candles/{symbol}`: cache by (market, resolution, end bucket) for the length of one bar, at most 60 s. Many users on BTC 15m cost one venue read a bar.
- `/api/funding/*`, `/api/oi/*`, `/api/liquidations*`: already from the database, and cached at Caddy by 2.10 rule 5.
- Every cache key is bounded by markets × resolutions, which is what D11 asks.

### 2.7 Types for the web app

- Response schemas move to `packages/core/src/api/*.ts` as zod schemas with the names `web/src/lib/api.gen.ts` exports today.
- `web/src/lib/api.gen.ts` becomes a re-export of `@mayedge/core/api`. `make api-types` is removed. `test_api_contract.py` and `test_api_types.py` become one Vitest that checks every route's response against its schema.

### 2.8 Logs

- JSON lines to stdout (`pino`). Never log a token, a cookie, `HEARTBEAT_URL` or a wallet signature. Port the `expect_logs.py` helper for tests that assert on logs.

### 2.9 The public budget invariant (D11)

- A test boots the server with a counting fake venue, connects 1, 10 and 100 fake tabs on 3 markets, runs 10 fake minutes, and asserts the public requests spent are the same for 10 and 100 tabs.

### 2.10 Market history

The market server is the only place market history exists. Most of it cannot be read back from Lighter, so what the server does not record is gone for every user.

| History | Recorded from | Kept | Can Lighter refill it? |
|---|---|---|---|
| OI samples, then OI hours | `market_stats/all`, one close per perp per UTC minute | samples 30 days, hours for good | No. Trades carry no open interest ([ADR 0008](../adr/0008-oi-is-a-sampled-level.md)) |
| Liquidations, then Liquidation days | the trade feed | fills 30 days, days for good | No. The desk does not read trade history (`recentTrades` is weight 600) |
| Funding estimates | `market_stats/all` | 30 days | No |
| Funding prints, then Funding days | the live feed, and the Funding backfill | for good | Partly. The venue keeps about 62 days of hours; the backfill reads up to a year of days |
| Alert rows and their Left and Against | the alert engine | as alert-rules.md says | No |
| Price hours | the market feed's 1m candles, folded each hour; one backfill of 365 days of 1h `candles` per Market | for good | Yes, once, on the `background` lane; Backtests read only these rows (Basket scope section 10) |

The rules:

1. **One recorder.** Only the market server writes these tables. A browser never records market history and the server never accepts it from one: a user could send anything.
2. **Seeded from the owner's desk.** The hosted desk starts with the owner's history, not an empty file (section 6.6). `/api/health` gains `history: {table: since_ms}` for each table above, so the first day of each series is visible.
3. **A gap is shown, never filled.** A minute the server missed stays missing (ADR 0008). The server writes its own downtime into a new table `recording_gaps (start_ms, end_ms, reason)` from `alive` (boot after a stop), the market feed (disconnected over 60 s) and loop watch (a Freeze). The history routes add a `gaps` list to their JSON; adding a field keeps D6. The OI pane, the Fund pane and Liquidation heat draw a gap as a break, not a line across it, and Liquidation intensity already refuses a window that is not fully sampled. Write the gap rule into CONTEXT.md (OI sample, Liquidation day, Funding print) and into a follow-up to ADR 0008 before the code (Ground rules, rule 6).
4. **A second recorder can fill a gap, later and optional.** The local Docker desk can keep recording public data. A merge job may copy its rows into a recorded gap and nowhere else: it never replaces a row the market server wrote. Only from a recorder the owner runs, never from a user.
5. **History routes are public and cacheable.** `GET /api/oi/{symbol}`, `/api/funding/{symbol}`, `/api/funding/{symbol}/average`, `/api/liquidations`, `/api/liquidations/summary`, `/api/candles/{symbol}` and `/api/markets*` need no session. They are the same for every user. The Host check still applies; the Origin check already covers only state-changing requests and the WebSocket.
   - The web app asks for history in two parts: the closed part, with `end` on the last closed UTC hour, and the live tail. A closed part answers with `Cache-Control: public, max-age=31536000, immutable` and an `ETag`; a live tail with `max-age=60`. Caddy caches both, so 500 users opening BTC's OI cost one database read per hour.
   - A closed part that holds a recorded gap is cached for 1 hour only, so a gap filled by rule 4 shows up.
   - Caddy limits these routes per IP (start at 300 a minute) because there is no session to count on.
6. **History has its own Backup.** It cannot be rebuilt; personal data can be synced again from Lighter.
   - Daily at 03:30 UTC, as today, the Backup is split in two: a history Backup (the tables above and `recording_gaps`) and a user Backup (everything with a `user_id`, and `users`, `venue_accounts`, `push_links`).
   - History Backups: keep 7 daily and 8 weekly. Once the VPS exists, copy each one off the host (any object store; the copy is encrypted before it leaves).
   - Once a month, restore the newest history Backup into a scratch folder and compare row counts with the live file. Write the result in the ops log.
7. **History grows with markets, not users.** OI samples stay at 30 days per perp; OI hours, Liquidation days and Funding prints grow by one row per perp per hour or day. Watch disk on `/api/health` and alert at 80%.
8. **The Funding backfill does not change.** Once per perp, then daily, on the server's `background` lane. It never depends on how many users there are.

Done for 2.10 when: the server records every table above; `recording_gaps` holds a stopped server's downtime and the OI pane draws it as a break; a closed history part is served from Caddy's cache on the second request; the history Backup and the user Backup restore separately.

**Done when:** the server boots against mainnet public data, the unchanged web app shows Chart, Scan, Watch, Alerts and Liqs from it, 2.9 passes, and 2.10 is done.

---

## ⏸ Checkpoint 1: shadow run

The Python desk keeps running on `:14200`. The market server runs on `:14300` against the same mainnet public data, with an empty database and then with a copy of the owner's database (read from a Backup, never the live file).

1. `scripts/parity-diff.ts` reads both every minute for 48 hours: `/api/scan/activity`, `/api/scan/tones`, `/api/alerts`, `/api/liquidations/summary`, `/api/funding/BTC/average`, `/api/oi/BTC`.
2. Pass: Activity and Tones match row for row on closed bars; alert rows match on (rule, market, minute) for 99% or more, with a 1-minute window for timing; Left and Against match to the fixture tolerance; OI and Funding match on closed hours.
3. Write every mismatch into the spikes doc with its cause. Fix the TypeScript, or write down why the Python was wrong and fix the rule doc first (rule 2).

---

## 3. Sign-in and per-user data

### 3.1 Tables

New migration:

| Table | Columns |
|---|---|
| `users` | `id`, `l1_address` (lowercase, unique), `created_at`, `last_seen_at` |
| `sessions` | `id` (random 32 bytes, stored hashed), `user_id`, `created_at`, `expires_at`, `user_agent` |
| `siwe_nonces` | `nonce`, `created_at` (5-minute life, single use) |
| `venue_accounts` | `user_id`, `account_index`, `api_key_index`, `read_token_enc`, `read_token_expires_at`, `chosen_at` |
| `push_links` | `user_id`, `chat_id`, `linked_at`; `push_link_codes` with `code`, `user_id`, `expires_at` |
| `user_settings` | `user_id`, `key`, `value` (Push knobs, Tone timeframes choice) |

The Journal tables (`journal_fills`, `journal_funding`, `journal_notes`, `journal_excursions`) also gain `account_index`, so a Basket's sub-account keeps its own Round trips (Basket scope section 11).

Per-user tables that exist today gain `user_id INTEGER NOT NULL REFERENCES users(id)` and indexes leading with `user_id`: `journal_fills`, `journal_funding`, `journal_notes`, `journal_excursions`, `portfolio_pnl`, `ideas`, `idea_log`, `idea_alerts`, `algo_runs`, `algo_clips`, `algo_fills`, `algo_trade_ids`, and Opened in `alert_rows` moves to `alert_opened (user_id, alert_id)`. The migration gives existing rows `user_id = 1`, the owner (section 6.6).

### 3.2 Isolation

- Every per-user query takes `userId` as its first parameter. A Vitest scans `server/src/db/*.ts` and fails if a statement touching a per-user table has no `user_id = ?`.
- A test signs in two fake users, writes for both, and checks each route returns only its own rows.

### 3.3 Sign-in flow

1. `GET /api/auth/nonce` → `{nonce}`.
2. The browser builds the EIP-4361 message: domain = `PUBLIC_ORIGIN` host, statement "Sign in to Mayedge. This does not move funds.", chain id 1, nonce, issued-at.
3. The wallet signs (`personal_sign`).
4. `POST /api/auth/verify {message, signature}`: check domain, nonce (then delete it), age under 5 minutes, signature (`viem`). Find or create the user. Set cookie `mayedge_session`: `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, 30 days.
5. `GET /api/me` → `{l1_address, accounts: [...], chosen_account, push_linked}`; `accounts` comes from `accountsByL1Address` (public, cached 5 minutes per address; this is a bounded per-user read, so it counts in the D11 test as sign-ins, not tabs).
6. `POST /api/auth/logout` deletes the session.

Externally owned accounts only in v1. A contract wallet (ERC-1271) needs an RPC call to verify; leave it for later and say so on the sign-in screen.

### 3.4 Guard

- Keep the Host and Origin checks from ADR 0005. Every state-changing route, every per-user route and the WebSocket upgrade also need a valid session. The market data and history routes in 2.5 and 2.10 rule 5 do not. `SameSite=Strict` plus the Origin check covers CSRF.
- Our own per-user limit on the API (start at 120 requests a minute per session) so one tab cannot load the server.

### 3.5 Per-user WebSocket

- `/ws` reads the session cookie on upgrade. Market messages go to every socket. User messages (`idea_alert`, `journal_open`, Push notices) go only to that user's sockets.
- The browser tells the server, over the socket, what only it knows: `{type: "held", markets: [...]}` when positions change, `{type: "auto_kill", armed, floor, target}` when Auto kill changes. The server uses them for Held market alerts, `/status` and the D5 Push.

### 3.6 The read-only token

- `PUT /api/me/read-token {account_index, token}`: the server checks the token's format and that it names `account_index`, calls `accountLimits` with it once, and stores it AES-256-GCM encrypted with `TOKEN_KEY`. The browser makes the token in section 4.4.
- `DELETE /api/me/read-token` drops it; Journal and Portfolio then stop syncing and say why.
- Never returned by any route, never logged.

### 3.7 Per-user jobs

Each job runs per user with a read-only token, on that user's own budget (section 7), and stops when the token expires or the venue refuses it.

| Python | Server module | Schedule | Requests a minute per user |
|---|---|---|---|
| `journal_sync.py`, `persist_journal.py` | `user/journalSync.ts` | every 5 min, and on the tab's fill notice | ≤ 2 on average |
| `portfolio_sync.py`, `portfolio_venue.py`, `persist_portfolio.py` | `user/portfolioSync.ts` | every 10 min, and when `/portfolio` opens | ≤ 1 |
| positions for Pushes (new) | `user/positionsPoll.ts` | every 60 s, only while Pushes are linked and no tab is connected | ≤ 1 |
| `idea_alert_watch.py`, `persist_idea_alerts.py` | `user/ideaAlertWatch.ts` | every 2 s, from the market feed | 0 (market data only) |
| Basket watch (new) | `user/basketWatch.ts`, `user/basketValues.ts` | Band mode every 5 min, Calendar at each due time, Basket value hourly, per live Basket | 0.2 per Band Basket; Paper Baskets 0 |

Total per user stays at or below 6 requests a minute. A user-job scheduler spreads users over the minute so 500 users do not all sync at :00.

### 3.8 Per-user routes

Same paths and JSON as today, now scoped to the session's user and chosen account:

- Journal: `GET /api/journal/trips`, `/api/journal/summary`, `/api/journal/open`, `/api/journal/trips/{trip_key}/excursion`, `PUT /api/journal/trips/{trip_key}/note`, `POST /api/journal/sync`.
- Portfolio: `GET /api/portfolio`, `/api/portfolio/history`, `/api/portfolio/days`.
- Ideas and Price alerts: every `/api/ideas*` and `/api/idea-alerts*` route, except `POST /api/ideas/{idea_id}/planner` (Start), which returns 404 until algos return.
- Alerts: `POST /api/alerts/{id}/opened`.
- Pushes: `GET /api/push`, `POST /api/push/test`, `POST /api/push/link` (returns a `t.me/<bot>?start=<code>` link).
- Tones: the server computes a fixed set of Tone timeframes (start with 15m, 30m, 1h, 4h, 1d); `PUT /api/scan/tones/timeframes` stores the user's two, and the Tones board filters to them. Write this into the Tones rules and Scan section of the README.

### 3.9 Pushes for many users

- One bot. `push_inbox.py` becomes `user/telegramInbox.ts`: `/start <code>` links a chat to a user and burns the code; `/status` answers that user from the last positions the server knows (the tab's `held` report, or the 60 s poll) and Auto kill as the tab last reported it; `/stop` unlinks.
- `push_router.py` routes per user: market alerts the user would see (Held market, Favorites are browser-only so Pushes use Held markets plus the user's own Price alerts), Near liquidation from the positions poll, Idea alerts, server down and Freeze to every linked user, and D5's "Auto kill stopped watching".
- Telegram allows about 30 messages a second per bot. Queue sends; drop duplicates the way `push_router.py` already does.
- Update `docs/push-rules.md` first (rule 6).

### 3.10 Algo routes in v1

`GET /api/algos` returns `{type: "algo", id: "algos", working: [], history: []}` so the web app renders. Every other `/api/algos*` route returns 404. The owner's old algo rows stay in the database for the Journal's by-algo breakdown.

### 3.11 Web app changes in this section

- A sign-in screen in front of the desk (connect wallet, sign, pick account). `/api/me` decides whether the desk or the sign-in screen shows.
- One build flag, `HOSTED`, read in one place. When it is on, `web/src/lib/algoPlugins` registers no algo, the Order panel's Algo tab, the Positions panel's Algos tab, Clip, Planner and Trail chart lines, and the Positions-row Plan and Trail entries are not rendered, and Idea **Start** is disabled with the sentence "Algos are not on the hosted desk yet."
- A Settings item for Pushes: the Telegram link, Send test, unlink.
- Nothing else in `web/src/components` changes in this section.

**Done when:** two testnet wallets sign in, each sees only their own Journal, Portfolio and Ideas, and the D5 Push and `/status` work through a linked Telegram chat.

---

## 4. Trading from the browser

All of it lives in `web/src/venue/`, behind the same functions `web/src/lib/api.ts` exports today, so components do not change. Test against the ported fakes and testnet only (D12).

### 4.1 Files

```
web/src/venue/
  signer.worker.ts   loads signer.wasm, holds the decrypted key, signs; nothing else
  signer.ts          typed messages to the worker
  vault.ts           encrypted key in IndexedDB
  onboarding/        the connect flow (4.4)
  nonce.ts           one nonce stream per key
  rest.ts            authenticated REST with the browser's RestBudget
  accountFeed.ts     port of lighter/account.py
  orders.ts          port of the sending half of lighter/orders.py
  kill.ts            wires core/kill.ts to orders.ts
  autoKill.ts        wires core/autoKill.ts to the account feed
  lock.ts            Web Locks (D4)
  health.ts          the tab's own feeds and sleep (4.10)
```

### 4.2 The signer

- Build `signer.wasm` from the pinned lighter-go tag (S3) in CI. Commit its SHA-256 in `web/src/venue/signer.sha256`; the worker checks the hash before instantiating.
- Serve it from our origin as `application/wasm`, Brotli compressed, never from a CDN.
- The worker is the only code that sees the raw private key. The main thread sends `{op: "createOrder", ...fields, nonce}` and gets back `{txType, txInfo, txHash}` or `{error}`. The worker never `fetch`es.
- Never pass nonce `-1` (the signer would try to fetch it and fail in WASM).

### 4.3 The key vault

- The key is encrypted with AES-GCM under a key derived from a passphrase (PBKDF2-SHA-256, 600,000 iterations, random salt), stored in IndexedDB with the account index and API key index.
- Unlock asks for the passphrase once per tab. Optional "lock after N minutes idle".
- "Session only" mode: keep the key in the worker's memory and never write it; it is gone when the tab closes, and onboarding runs again.
- "Forget this device" deletes the record. "Revoke key" (from S9) replaces the key on the venue.
- Section S8's answer goes into the sign-up text: say plainly what someone who steals this key could do.

### 4.4 Connecting an account

1. Connect a wallet (EIP-1193 through `viem`; MetaMask and Rabby tested).
2. Sign in (3.3).
3. Pick an Account index from `/api/me`. One account per user in v1.
4. Read the account's API keys (`apikeys`, index 255 = all). Offer the first free index in 4–254. **Never overwrite a used index without a second, explicit confirm naming it**: that would cut off whatever bot uses it.
5. `GenerateAPIKey` in the worker.
6. `nextNonce` for (account, index); `SignChangePubKey`; the wallet signs what S4 found; `sendTx`.
7. Poll `accountLimits` with an auth token from the new key until 200 (up to 30 s).
8. Ask for a passphrase (or Session only); write the vault.
9. Create a read-only token (single account, 365 days) and `PUT /api/me/read-token`. This costs 10,000 request weight, so it is made once and refreshed 7 days before it expires, when a tab is open.
10. Done screen: "Your key stays in this browser. Mayedge's server cannot trade for you. Closing this tab stops Auto kill."

An **Advanced** path takes a key the user made at app.lighter.xyz (index and private key pasted into the worker). Same vault, same steps 7–10.

### 4.5 Nonces

- One stream per (account, API key index). Fetch `nextNonce` at unlock, then count locally.
- On `INVALID_NONCE` (`21104`): fetch again and retry once, as `_retry_nonce` does. A `code: 200` can still use a nonce; follow lighter-limits.md's Nonce section.
- Only the tab holding the Web Lock sends.

### 4.6 The browser's budget

- A `RestBudget` from `core` per tab, for the chosen account: 48 requests (54 less the server's 6 from section 3.7) and 38 sends a rolling minute. The Kill lane is never refused.
- Authenticated REST counts on the wallet (S7), which also covers the server's per-user jobs, hence the 6.
- `budget` messages go to the header readout as today.

### 4.7 The account feed

- Port `lighter/account.py` into `accountFeed.ts`: subscribe `user_stats`, `account_all_orders`, `account_all_trades`, `account_all_positions`, `account_all_assets` with an auth token; refresh the token every 6 hours (it lasts 8 at most); merge the way `account.py` merges; resync over REST after a reconnect.
- It emits the same `account` and `account_trades` messages into the same place `useMarketWs.ts` handles them today. Give the hook a second source, not a second set of handlers.
- `GET /api/account`, `/api/account/trades`, `/api/account/funding` in `api.ts` read from the feed and authenticated REST instead of the server.

### 4.8 Orders, Kill, Auto kill

- `api.ts` keeps `placeMarketOrder`, `placeLimitOrder`, `placeTwapOrder`, `placeStopTake`, `cancelOrder`, `amendOrder`, `cancelSide`, `cancelAll`, `updateLeverage`, `kill`, `getAutoKill`, `putAutoKill`, and calls `venue/` instead of the server.
- Order building and checks come from `core/venue/orderBuild.ts`: maker minimums at the order's own price, the notional cap (`max_order_notional`, 50,000 by default, now a user setting), trigger side, worst price for market orders and Kill.
- Manual Tickets use the Manual client_order_index band `[1e9, 8e9)`. Leave the other bands unused.
- Kill: `cancel all orders` (immediate, every market), then flatten when asked, at `FLATTEN_SLIPPAGE`, through the Kill lane.
- Auto kill: `core/autoKill.ts` on the account feed's uPnL, (mark − entry) × size, as today. It watches uPnL only, on purpose. The armed badge says "this tab". It reports armed and disarmed to the server (3.5).
- Fill notices, order notices and the chart's Ticket lines keep working from the account feed.

### 4.9 One tab

- `navigator.locks.request("mayedge-signer-<account>-<index>", ...)` at unlock. The tab that holds it trades. Any other tab shows the desk read-only with a line: "Trading is open in another tab."
- The Watch popout keeps sharing the desk tab's feed and still dies with it.

### 4.10 The tab reports its own absence

- `health.ts` notices a sleep (a timer that wakes late by more than 10 s) or a hidden tab (`visibilitychange`) while Auto kill is armed, and says so in the header and in the D5 Push. ADR 0019 becomes true for the tab too.

**Done when:** on testnet, every row of section 0's transaction list works from the hosted desk; Kill cancels and flattens; Auto kill fires on a fake uPnL floor; a second tab is read-only; the vault survives a reload with a passphrase and is gone in Session only mode.

---

## 5. The browser reads its own market

Only if S1 and S2 passed.

- The chart's market (`order_book/{i}`, `trade/{i}`, `candle/{i}/{res}`) moves to a direct Lighter WebSocket in the browser. Port the book merge from `order_book.py` into `core` so both sides share it.
- `/api/candles` stays on the server as the fallback and for Scan and Watch history.
- The server stops following tab markets (2.3) and drops the cap.
- The browser's public WebSocket stays well under Lighter's per-IP limits: one connection, at most 3 markets (chart, plus Watch).

**Done when:** 2.9's test shows the server spends nothing per tab market, and the chart is unchanged.

---

## B. Baskets

The scope is [2026-10-basket-scope.md](2026-10-basket-scope.md), with its own order (its section 15). Where it joins this plan:

| Basket step | Needs from this plan | Lands as |
|---|---|---|
| Words, rules, ADRs; `core/basket` | section 1 | part of B1 |
| Price hours | section 2.10 | part of B1 |
| Paper Baskets, Basket page, Backtests | section 3 (sign-in, per-user tables, Pushes) | **B1**: a product with no key at all, so it can open to users before trading does |
| Spot orders, sub-accounts, Go live | section 4 and spikes S11–S14 | part of B2 |
| The Rebalancer, review and run | section 4 (signer, nonces, budget, account feed) | **B2** |
| Journal and Portfolio by account | section 3.8 | part of B2 |

Section 3.11's `HOSTED` flag hides every algo except the Rebalancer. The Rebalancer's client_order_index band is `[13e9, 14e9)`.

**Done when:** B1, a Paper Basket runs for a week on the server with no tab, and a Backtest of it over 90 days returns in under 5 seconds; B2, the Basket scope's testnet live Basket is built, Rebalanced and closed.

---

## ⏸ Checkpoint 2: testnet beta

1. Deploy to a staging host with `LIGHTER_NETWORK=testnet`. Only invited testers with fresh testnet wallets.
2. Two weeks. Each day, one tester runs the checklist: sign in, connect, every transaction row, Kill, Auto kill in a tab, second tab, Push link and `/status`, Journal and Portfolio fill in, an Idea with a Price alert fires a Push while no tab is open, a Paper Basket Rebalances on its own, a live Basket's due Rebalance arrives as a Push and is approved and run from the tab.
3. Watch: venue 429 and 405 (target zero), `INVALID_NONCE` rate, Push delays, loop lag, database size per user.
4. Fix, then repeat the checklist on the fixed build.

---

## 6. Hardening and launch

### 6.1 Browser security

- Content-Security-Policy from Caddy: `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self' https://mainnet.zklighter.elliot.ai wss://mainnet.zklighter.elliot.ai; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`. No third-party script, font or analytics.
- `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` with everything off.
- Audit every `dangerouslySetInnerHTML` and every place an Idea's Thesis, a note or a market name is rendered. User text is text.
- `npm audit` in CI; lockfiles committed; no `postinstall` scripts allowed from dependencies (`ignore-scripts`).

### 6.2 Server security

- Secrets only in `server/.env`. `TOKEN_KEY` and `SESSION_SECRET` are 32 random bytes.
- Backups contain encrypted read-only tokens; `TOKEN_KEY` is never inside a Backup.
- Fail closed: an unknown route, a bad session or a bad Origin is refused with no detail.

### 6.3 Deployment

- When the VPS exists: `docker-compose.yml` with `server` and `caddy`; the database on a named volume; Backups to a host folder, as today, and history Backups copied off the host (2.10 rule 6). Nothing here assumes a provider.
- `/api/health` for the Heartbeat service, as today.

### 6.4 Observability

- Request counts and errors per route; venue requests per lane and 429s; WebSocket connections; per-user job lag; Push queue length. Expose `/api/health` detail only to the owner's session.

### 6.5 Words and pages

- A sign-up screen and a short page: what the server can and cannot do (D1, D3), what tab-bound means (D5), not financial advice.
- README and CONTEXT.md describe the hosted desk.

### 6.6 Moving the owner's data

1. Take a Backup of the live desk (`make backup`).
2. Run the server's migrations on a copy. Every per-user row gets `user_id = 1`. The market history tables (2.10) are kept as they are: they become every user's history. Record each one's first day for `/api/health`.
3. Fill `recording_gaps` for the time between the Backup and the hosted desk's first recorded minute, so that switch-over shows as a gap and not as a line.
4. The first sign-in from `OWNER_L1_ADDRESS` takes user 1.
5. Compare row counts for every table before and after; write them in the commit message.

### 6.7 Launch

1. The owner connects the mainnet account on the hosted desk, places one small limit Ticket by hand far from the touch, cancels it, and checks both on app.lighter.xyz.
2. The owner trades on the hosted desk for one week while the local desk stays up with no key loaded, for comparison.
3. Then open invites.

### 6.8 Retire the Python

Two weeks after launch with no blocking bug: delete `backend/`, its CI job and its make targets, in one commit. ADR 0005 is marked superseded.

---

## 7. Rate limits, all in one place

Lighter Standard: 60 requests a rolling minute, sends inside the 60, 40 default-type transactions a minute. Keys per the rate-limit page (S7 confirms the read-only case).

| Who spends | Keyed by | Ceiling | What |
|---|---|---|---|
| Market server, public | Server IP | 54/min total, whatever the number of users (D11) | `orderBookDetails`, Scan and alert candles, funding backfill, OI, `accountsByL1Address` on sign-in |
| Market server WebSocket | Server IP | one connection, public channels only | `market_stats/all`, `trade/*`, `candle/*` for alerts; the tab market set until section 5 |
| Market server, per user | That user's wallet | ≤ 6/min per user | Journal, Portfolio, Positions poll, read-only token check |
| Browser, REST | That user's wallet (authenticated) | 48/min | account resync, `nextNonce`, `apikeys`, onboarding |
| Browser, sends | That user's wallet | 38/min, Kill never refused | every transaction in section 0's list |
| Browser WebSocket | User's IP | one connection for the account, one for its market | account channels; chart market from section 5 |

A 429 or 405 starts a 60 s cooldown for whoever got it. On the browser that is the user's own wallet; on the server it would stop Scan and Alerts for everyone, which is why the server's public lanes stay where `budget.py` puts them today.

---

## 8. Later: algos in the tab

Not part of this plan, except the Rebalancer (section B). What the next plan has to answer, written down now so v1 does not block it:

- Algos run in the tab's Worker and stop with it (the same deal as Auto kill).
- Every position an algo opens gets a venue Stop at once, so a closed tab leaves it protected.
- Algo Clips carry a short expiry (the venue's minimum is 5 minutes) and are renewed while running, so a closed tab leaves nothing behind for long. Check post-only orders take an expiry.
- On reopen, the client_order_index bands say which algo left which order; the desk asks before it resumes anything.
- Lighter's scheduled cancel-all (`CANCEL_ALL_TIF_SCHEDULED` in the signer) looks like a dead man's switch but would likely cancel the venue Stops too. Test before using it.
- The algo code moves into `core` with its 11k lines and its harness tests, the same way as section 1.

---

## Risks

| Risk | What it costs | What this plan does |
|---|---|---|
| Lighter refuses browser origins (S1, S2) | Section 5 is gone; reads go through the server, which caps users | Relay; write the cap down |
| A script on our page steals a key | Someone trades the user's account | D1 limits it to one user; CSP and no third-party code (6.1); the key only in a Worker; S8 tells users what is at stake |
| The port drifts from the rules | The hosted desk alerts or computes differently | Tests first, parity fixtures, the shadow run |
| `better-sqlite3` blocks the loop | Lag for every user | Slow reads in worker threads (2.2); loop lag watched |
| The market server is down | Every user loses that stretch of OI, Liquidations and Funding estimates for good | Gaps recorded and shown (2.10 rule 3); Heartbeat; an optional second recorder (2.10 rule 4) |
| The history file is lost | Months of history no venue can give back | Split history Backup, off-host copy, monthly restore drill (2.10 rule 6) |
| Read-only tokens cannot do what the server needs (S6) | Journal and Portfolio sync only while a tab is open | Fallback in S6 |
| Users overwrite an API key index used by their own bot | Their bot stops | The explicit second confirm in 4.4 |
| Pushes flood Telegram with many users | Delays | Queue and dedupe (3.9) |
| Hosting a trading front end for others has legal and venue terms | Unknown | Owner checks Lighter's terms for third-party front ends before inviting anyone (open question 5) |

---

## Open questions for the owner

1. Who gets in: invite-only, or anyone with a wallet?
2. The domain, and whether a staging host exists for checkpoint 2.
3. One account per user, or sub-accounts too?
4. Passphrase by default, or Session only by default?
5. Lighter's terms for third-party front ends. The signer has `integrator_account_index` and `integrator_taker_fee`, so Lighter expects them; whether Mayedge ever takes a fee is a separate decision.
6. Wallets beyond MetaMask and Rabby (WalletConnect for phones)?

---

## What "done" means

The hosted desk is done when an invited user, on mainnet:

- signs in with their wallet and connects their Lighter account without pasting anything;
- sees the same Chart, Scan, Watch, Alerts, Liqs, Positions, Journal, Portfolio and Ideas the local desk shows today;
- places, amends and cancels every **Ticket** kind, sets leverage, and uses **Kill**, all signed in their own browser;
- arms **Auto kill** and is told, on screen and by **Push**, that it lives in the tab;
- gets **Pushes** in their own Telegram chat with no tab open;
- builds a Basket, runs it on paper, Backtests it, takes it live in its own sub-account, and approves its Rebalances from the tab;

and the market server holds no API private key, spends the same public requests for 100 users as for 10, and passes `make ci`.
