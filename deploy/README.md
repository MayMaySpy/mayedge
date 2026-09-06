# Mayedge on a VPS (Tailscale only)

The desk has **no login**. Anyone who can reach the HTTP port can trade, run algos, and flatten. The ACL is Tailscale, not the app.

This is the intended production shape: Docker on a VPS, host port **loopback only**, remote access **Tailscale Serve only**. Never Funnel. Never `0.0.0.0:14200`.

## What “correctly exposed” means

```
laptop / phone  --(tailnet TLS)-->  MagicDNS :443  --(Serve)-->  127.0.0.1:14200  --(docker)-->  app :8000
                                      ▲
                                      only identities in group:mayedge-admins
```

| Piece | Binding | Who can hit it |
|---|---|---|
| App inside the container | `0.0.0.0:8000` | Docker network only |
| Host publish | `127.0.0.1:14200` | Processes on the VPS |
| Tailscale Serve | `https://<machine>.<tailnet>.ts.net` | Tailnet + ACL |
| Funnel | **off** | would be the public internet |

Compose already does the host bind correctly:

```yaml
ports:
  - "127.0.0.1:14200:8000"
```

That is **not** on the public NIC and **not** on the Tailscale `100.x` address. Do not change it to `"14200:8000"` — Docker would then listen on `0.0.0.0` (and punch past UFW). Do not open `:14200` on the VPS firewall.

On another tailnet device, use the **Serve HTTPS URL**, not `http://100.x:14200`. The `100.x` port is closed on purpose; Serve is the door, and it is identity-aware.

The UI, `/api`, and `/ws` are the same origin. The browser opens `wss://<magicdns>/ws` when you load the Serve URL over HTTPS. No extra CORS or proxy.

## Once on the VPS

1. Docker Engine + Compose plugin.
2. Tailscale (`curl -fsSL https://tailscale.com/install.sh | sh`).
3. `sudo tailscale up` — log in. Then `sudo tailscale set --operator=$USER` so `serve` does not need root.
4. Cloud firewall (Hetzner etc.): allow **22** until Tailscale SSH works; do **not** allow 14200, 8000, 80, or 443 from the world. Serve traffic stays on the tailnet, not public 443.

Laptop `~/.ssh/config`:

```
Host mayedge
  HostName <vps-ip-or-magicdns>
  User <you>
```

Override with `make deploy VPS=user@host` if the host alias is different.

## Tailscale ACL

Admin console → **Access controls** → JSON editor. Paste [tailscale-acl.hujson.example](tailscale-acl.hujson.example), replace `YOUR_EMAIL` with the Google/GitHub address you use to log into Tailscale.

Then **Machines** → **the VPS** (not your laptop) → tags → `tag:mayedge-vps`.

This ACL only allows your group to that node’s **22** and **443**. It does not grant Funnel. Do not add `"attr": ["funnel"]` to `nodeAttrs`.

## First deploy (laptop)

```bash
cp backend/.env.example backend/.env   # fill Lighter keys if trading
make push-env
make deploy
make check
```

`make deploy` rsyncs the tree to `/opt/mayedge` (skips `.env`, venv, `node_modules`), builds the image on the VPS, and runs:

```bash
tailscale serve --bg http://127.0.0.1:14200
```

That persists in Tailscale across reboots. Docker `restart: unless-stopped` brings the container back.

Open the HTTPS URL printed by `tailscale serve status` (on the box) or in the Tailscale admin machine page. On the VPS itself: `http://127.0.0.1:14200`.

## Day to day

| Command | Does |
|---|---|
| `make deploy` | rsync → `docker compose up -d --build` → Serve |
| `make push-env` | copy `backend/.env` to the VPS (`600`). Not part of `deploy` |
| `make serve` | re-apply Serve only |
| `make check` | loopback bind, health, SPA, Serve target, Funnel off |
| `make logs` | follow container logs |
| `make down` | `docker compose down` on the VPS (volume kept) |

Local laptop Docker (optional): `make up` / `make down-local` / `make logs-local`.

## Never

- `tailscale funnel …` — public internet to the desk. If `make check` says Funnel is on: `tailscale funnel reset`.
- Publish `"14200:8000"` or bind the app to a public NIC.
- Put nginx/Caddy on `:80`/`:443` for this app. Serve is the TLS terminator.
- Commit `backend/.env`. `make deploy` excludes it; `make push-env` is the only copy path.

## Verify by hand

On the VPS:

```bash
ss -ltn | grep 14200          # 127.0.0.1:14200 only
curl -sf http://127.0.0.1:14200/api/health
tailscale serve status        # proxy → http://127.0.0.1:14200
tailscale funnel status       # not “Funnel on”
```

From a tailnet laptop: open `https://<machine>.<tailnet>.ts.net`. From a browser **not** on the tailnet: that URL must fail.
