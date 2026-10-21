"""Wall time of the heavy desk reads. Never points at the live Docker volume.

    uv run python scripts/profile_reads.py /path/to/copy.db
"""

from __future__ import annotations

import cProfile
import pstats
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from mayedge.config import settings


def _refuse_volume(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SystemExit(f"not a file: {resolved}")
    text = str(resolved)
    if "/docker/volumes/" in text or text.startswith("/app/data"):
        raise SystemExit(f"refusing {resolved}: it is inside the Docker volume")
    try:
        mount = subprocess.check_output(
            ["docker", "volume", "inspect", "-f", "{{.Mountpoint}}", "mayedge_mayedge-data"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        mount = ""
    if mount and (text == mount or text.startswith(mount.rstrip("/") + "/")):
        raise SystemExit(f"refusing {resolved}: it is inside the Docker volume")
    return resolved


def _btc(path: Path) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT market_index FROM oi_samples WHERE symbol = 'BTC' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise SystemExit("the copy has no BTC open-interest sample")
    return int(row[0])


def _times(fn: Callable[[], object], rounds: int = 5) -> tuple[float, float]:
    first = None
    best = None
    for _ in range(rounds):
        started = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - started
        if first is None:
            first = elapsed
        best = elapsed if best is None else min(best, elapsed)
    assert first is not None and best is not None
    return first, best


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: profile_reads.py COPY.db")
    path = _refuse_volume(Path(sys.argv[1]))
    settings.db_path = str(path)
    btc = _btc(path)

    from mayedge.api.routes.journal import _closed_since, _trips
    from mayedge.journal import summary
    from mayedge.persist_funding import funding_averages, list_funding
    from mayedge.persist_liq import liquidation_summary_since_ms, summarize_liquidations
    from mayedge.persist_oi import fold_open_interest, list_open_interest
    from mayedge.persist_portfolio import portfolio_buckets

    since = int(time.time()) - 30 * 86_400

    def journal_trips() -> None:
        _trips()

    def journal_summary() -> None:
        chosen = [trip for trip in _trips() if _closed_since(trip, since)]
        summary(chosen, "none")

    calls = [
        ("journal trips", journal_trips),
        ("journal summary", journal_summary),
        ("oi BTC 1m", lambda: list_open_interest(btc, resolution="1m", count=500)),
        ("funding BTC 1h", lambda: list_funding(btc, resolution="1h", count=500)),
        ("funding average BTC", lambda: funding_averages(btc)),
        (
            "liquidations 24h",
            lambda: summarize_liquidations(since_ms=liquidation_summary_since_ms(24)),
        ),
        ("portfolio 7d", lambda: portfolio_buckets("1h", "pnl", 0)),
        ("oi fold", lambda: fold_open_interest(now_ms=int(time.time() * 1000))),
    ]

    print(f"db {path}  BTC market_index={btc}")
    print(f"{'call':<22} {'first':>12} {'best of 5':>12}")
    for name, fn in calls:
        first, best = _times(fn)
        print(f"{name:<22} {first * 1000:10.1f} ms {best * 1000:10.1f} ms")

    profile = cProfile.Profile()
    profile.enable()
    for _name, fn in calls:
        fn()
    profile.disable()
    stats = pstats.Stats(profile, stream=sys.stdout)
    stats.sort_stats("cumulative")
    stats.print_stats(25)


if __name__ == "__main__":
    main()
