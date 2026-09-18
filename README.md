# Mayedge

Personal perp trading desk — Python backend + React frontend. Lighter only.

![Mayedge desk](docs/ui.png)

Personal software, not a product. There is no login: anyone who can reach the HTTP port can trade. Not financial advice.

## Features

**Desk.** Resizable mosaic: Chart, Book, Trades, Order, Alerts, Liqs, Positions. Header has Market picker, Favorites, mark, funding, open interest, margin. Layout edit is opt-in.

**Chart panel.** One panel, three modes — not extra mosaic tiles.

- **Price chart** — candles, volume, Top of Book. Working Tickets draw on the chart: drag the line to Amend, click X to cancel. Clips are display-only. Armed **Axis** click on the price scale rests a GTT Ticket at Quick size (below live price buys, above sells).
- **Scan** — Relative Strength vs BTC, and liquidation heat over a 1h / 4h / 24h window.
- **Watch** — Path charts for a Watch Set (cap 8). Can undock to its own window; the popout shares the desk feed and dies with the desk tab.

**Execution.** Market and limit Tickets from the Order panel. Floating Buy/Sell are market at Quick size (the same size Axis rest uses). On the Orders tab, **Bids** and **Asks** cancel Tickets of that side in the current All/Market scope; Clips stay with the algo. **Kill** stops all algos then cancels working orders; flatten is optional, not implied.

**Algos.** Chase, Grid, Ladder, TWAP. Each owns Clips, not Tickets. Grid will not start on a Market that already has another desk algo live. Jobs persist in SQLite; start / pause / stop from the blotter.

**Feed.** Lighter WebSocket fan-out. Public market data works without keys. Testnet or mainnet via `LIGHTER_NETWORK` in backend `.env`.

Desk language is [CONTEXT.md](CONTEXT.md). Hard-to-reverse calls are in [docs/adr](docs/adr).

## Production

A VPS with **Tailscale Serve only**. Setup, ACL, and checks: **[deploy/README.md](deploy/README.md)**.

```bash
cp backend/.env.example backend/.env   # fill keys if trading
make push-env
make deploy
make check
```

Compose publishes `127.0.0.1:14200` (not `0.0.0.0`). Do not Funnel. Do not expose `:14200` on the public NIC.

**Local dev:** `uv run mayedge` binds `127.0.0.1:8000`; Vite proxies `/api` and `/ws`. Or `make up` for the same Docker image as production.

## Quick start (local dev)

### Backend

```bash
cd backend
cp .env.example .env
# Optional: add LIGHTER_ACCOUNT_INDEX, LIGHTER_API_KEY_INDEX (2-254), LIGHTER_API_PRIVATE_KEY
uv sync
uv run mayedge
```

API runs at `http://127.0.0.1:8000`. Public market data works without credentials.

### Frontend

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:5173`.

## API key setup (Lighter)

Use the [lighter-python examples](https://github.com/elliottech/lighter-python/blob/main/examples/README.md) `system_setup.py` with API key index **2–254** (not 0/1, reserved for the official app).

## Algos

Algos work in **Clips** (child working orders). Tickets on the chart are operator-placed; dragging a Ticket Amends it, a Clip does not.

### Chase

Accumulate or distribute via one-sided post-only Clips behind the touch. Amends in place (no cancel+replace). Pulls Clips when the book or account feed is unhealthy or price leaves your band. Stops when the parent size is filled.

Chase jobs persist in SQLite. On shutdown, venue Clips are **pulled**; on restart the parent **auto-resumes quoting** once market and account feeds are healthy (remaining qty is the source of truth). Dirty crash leftovers are pulled on boot; Resume/restore credit REST trades before quoting.

### Grid

Chases inside a price band and takes profit with reduce-only Clips. Exclusive on a Market: will not start if another desk algo is already live there.

### Ladder

Keeps N live rungs on static prices across a range; refills on fill.

### TWAP

Slices a parent size across time into Clips.

## Notes

- Docker publishes `127.0.0.1:14200` → app `:8000` (API, `/ws`, and the SPA). Remote access is Tailscale Serve.

## License

MIT. See [LICENSE](LICENSE).
