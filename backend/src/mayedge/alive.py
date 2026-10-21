"""An alive mark in the desk database, so a boot can say how long it was down."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from mayedge.db import _connect, _has_meta, _lock, _set_meta

logger = logging.getLogger(__name__)

ALIVE_AT = "alive_at"
CLEAN_STOP_AT = "clean_stop_at"
MARK_S = 30.0

_last_down: dict[str, int | bool] | None = None


def last_down() -> dict[str, int | bool] | None:
    return _last_down


def _read_ms(key: str) -> int | None:
    with _lock:
        conn = _connect()
        if not _has_meta(conn, key):
            return None
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return None


def _write(key: str, now_ms: int) -> None:
    with _lock:
        conn = _connect()
        _set_meta(conn, key, str(int(now_ms)))
        conn.commit()


def write_alive(now_ms: int) -> None:
    _write(ALIVE_AT, now_ms)


def mark_clean(now_ms: int) -> None:
    try:
        _write(CLEAN_STOP_AT, now_ms)
    except Exception:
        logger.exception("clean stop mark failed")


def note_boot(now_ms: int, down_after_s: float) -> dict[str, int | bool] | None:
    """Read the last marks. A fresh database, or a short gap, reports nothing."""
    global _last_down
    alive = _read_ms(ALIVE_AT)
    if alive is None or now_ms - alive < down_after_s * 1000:
        _last_down = None
        return None
    clean_at = _read_ms(CLEAN_STOP_AT)
    gap: dict[str, int | bool] = {
        "from": alive,
        "to": int(now_ms),
        "clean": clean_at is not None and clean_at >= alive,
    }
    _last_down = gap
    return gap


async def mark_once(now_ms: int) -> None:
    await asyncio.to_thread(write_alive, now_ms)


async def run_alive(
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    now_ms: Callable[[], int] | None = None,
) -> None:
    stamp = now_ms or (lambda: int(time.time() * 1000))
    while True:
        await mark_once(stamp())
        await sleep(MARK_S)


def start_alive() -> asyncio.Task[None]:
    return asyncio.create_task(run_alive(), name="alive")
