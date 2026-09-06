#!/usr/bin/env bash
# Run on the VPS (make check). Fails if the desk is public, Funnel is on, or Serve is missing.
set -euo pipefail

ROOT="${MAYEDGE_ROOT:-/opt/mayedge}"
PORT=14200
fail=0

say() { printf '\n== %s ==\n' "$1"; }

ok() { printf '  ok    %s\n' "$1"; }
bad() {
  printf '  FAIL  %s\n' "$1" >&2
  fail=1
}

say "loopback bind :${PORT}"
listen=$(ss -ltn 2>/dev/null || netstat -ltn)
if printf '%s\n' "$listen" | grep -Eq '0\.0\.0\.0:14200|\*:14200|\[::\]:14200'; then
  bad "14200 is on 0.0.0.0 / * — compose must publish 127.0.0.1:14200:8000"
  printf '%s\n' "$listen" | grep 14200 >&2 || true
elif printf '%s\n' "$listen" | grep -q '127.0.0.1:14200'; then
  ok "127.0.0.1:14200 only"
else
  bad "nothing listening on 127.0.0.1:14200 (is compose up?)"
fi

say "http health"
if curl -sf --max-time 3 "http://127.0.0.1:${PORT}/api/health" | grep -q '"status"'; then
  ok "/api/health"
else
  bad "/api/health did not return status=ok"
fi

if curl -sf --max-time 3 "http://127.0.0.1:${PORT}/" | grep -q '<div id="root"'; then
  ok "SPA shell"
else
  bad "GET / missing SPA shell (WEB_ROOT / image build?)"
fi

say "compose"
if [ -f "$ROOT/docker-compose.yml" ]; then
  if docker compose -f "$ROOT/docker-compose.yml" ps --status running --services 2>/dev/null | grep -qx mayedge; then
    ok "service mayedge running"
  else
    bad "compose service mayedge not running"
    docker compose -f "$ROOT/docker-compose.yml" ps >&2 || true
  fi
else
  bad "missing $ROOT/docker-compose.yml"
fi

say "env"
if [ -f "$ROOT/backend/.env" ]; then
  if grep -q '^LIGHTER_API_PRIVATE_KEY=.\+' "$ROOT/backend/.env"; then
    ok "backend/.env present (key set)"
  else
    ok "backend/.env present (trading disabled — empty key)"
  fi
  perm=$(stat -c '%a' "$ROOT/backend/.env" 2>/dev/null || stat -f '%OLp' "$ROOT/backend/.env")
  case "$perm" in
    600 | 400) ok "backend/.env mode $perm" ;;
    *) bad "backend/.env mode $perm (want 600)" ;;
  esac
else
  bad "missing $ROOT/backend/.env — run make push-env"
fi

say "tailscale serve"
if ! command -v tailscale >/dev/null; then
  bad "tailscale not installed"
elif ! tailscale status >/dev/null 2>&1; then
  bad "tailscale not logged in (sudo tailscale up)"
else
  st=$(tailscale serve status 2>/dev/null || true)
  if printf '%s' "$st" | grep -q "127.0.0.1:${PORT}"; then
    ok "Serve → 127.0.0.1:${PORT}"
    printf '%s\n' "$st" | sed 's/^/  /'
  else
    bad "Serve not pointing at 127.0.0.1:${PORT}"
    printf '%s\n' "$st" | sed 's/^/  /' >&2
    echo "  fix: tailscale serve --bg http://127.0.0.1:${PORT}" >&2
  fi
fi

say "tailscale funnel (must be off)"
if command -v tailscale >/dev/null; then
  fs=$(tailscale funnel status 2>/dev/null || true)
  if printf '%s' "$fs" | grep -qi 'funnel on'; then
    bad "Funnel is on — turn it off. Never Funnel this desk."
    printf '%s\n' "$fs" | sed 's/^/  /' >&2
  else
    ok "off"
  fi
fi

if [ "$fail" -ne 0 ]; then
  echo >&2
  echo "fail" >&2
  exit 1
fi

echo
echo "ok — desk is loopback + Tailscale Serve only"
