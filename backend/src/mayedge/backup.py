"""Daily Backups of the desk database, taken off the event loop."""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import logging
import os
import shutil
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from mayedge.config import settings
from mayedge.push import Clock

logger = logging.getLogger(__name__)

_BOOT_WAIT_S = 10 * 60
_active: BackupLoop | None = None


class _Pusher(Protocol):
    def push(self, key: str, text: str, *, urgent: bool = False, force: bool = False) -> None: ...


class _WallClock:
    def now(self) -> float:
        return time.time()

    def mono(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _seconds_until(now: datetime, hhmm: str) -> float:
    hour, minute = int(hhmm[:2]), int(hhmm[3:])
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _quick_check(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("PRAGMA quick_check").fetchone()
    finally:
        conn.close()
    if row is None or row[0] != "ok":
        detail = row[0] if row else "empty"
        raise RuntimeError(f"quick_check failed: {detail}")


def _gzip(src: Path, dest: Path) -> None:
    with src.open("rb") as inp, dest.open("wb") as out:
        with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
            shutil.copyfileobj(inp, gz)
        out.flush()
        os.fsync(out.fileno())


def _prune(dest_dir: Path, keep: int) -> None:
    files = sorted(dest_dir.glob("mayedge-*.db.gz"))
    if keep >= len(files):
        return
    for old in files[: len(files) - keep]:
        old.unlink()


def take_backup(db_path: Path, dest_dir: Path, *, now: datetime) -> Path:
    """Consistent gzip of db_path. The rename is the commit point."""
    now = _utc(now)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%S%f")
    day = now.strftime("%Y-%m-%d")
    raw = dest_dir / f".mayedge-{stamp}.db.tmp"
    gz_tmp = dest_dir / f"mayedge-{day}.db.gz.tmp"
    gz = dest_dir / f"mayedge-{day}.db.gz"
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        escaped = str(raw).replace("'", "''")
        conn.execute(f"VACUUM INTO '{escaped}'")
    finally:
        conn.close()
    try:
        _quick_check(raw)
        _gzip(raw, gz_tmp)
        os.replace(gz_tmp, gz)
    except Exception:
        raw.unlink(missing_ok=True)
        gz_tmp.unlink(missing_ok=True)
        raise
    raw.unlink(missing_ok=True)
    _prune(dest_dir, settings.backup_keep)
    return gz


class BackupLoop:
    """One task: catch up 10 minutes after boot, then run at backup_at UTC."""

    def __init__(
        self,
        db_path: Path,
        dest_dir: Path,
        at: str,
        clock: Clock,
        pusher: _Pusher | None = None,
        take: Callable[..., Path] = take_backup,
    ) -> None:
        self._db_path = db_path
        self._dest = dest_dir
        self._at = at
        self._clock = clock
        self._pusher = pusher
        self._take = take
        self._task: asyncio.Task[None] | None = None
        self.last_backup_at: int | None = None
        self.last_backup_bytes: int | None = None
        self.last_backup_error: str | None = None

    def start(self) -> None:
        global _active
        _active = self
        self._task = asyncio.create_task(self.run(), name="backup")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def run(self) -> None:
        await self._clock.sleep(_BOOT_WAIT_S)
        await self.run_once(catch_up=True)
        while True:
            now = datetime.fromtimestamp(self._clock.now(), UTC)
            await self._clock.sleep(_seconds_until(now, self._at))
            await self.run_once(catch_up=False)

    async def run_once(self, *, catch_up: bool = False) -> None:
        now = datetime.fromtimestamp(self._clock.now(), UTC)
        if catch_up and (self._dest / f"mayedge-{now:%Y-%m-%d}.db.gz").is_file():
            return
        try:
            path = await asyncio.to_thread(self._take, self._db_path, self._dest, now=now)
        except Exception as exc:
            logger.exception("backup failed")
            self.last_backup_error = str(exc)
            if self._pusher is not None:
                self._pusher.push("backup", f"⚠️ Backup failed: {exc}")
            return
        self.last_backup_at = int(now.timestamp() * 1000)
        self.last_backup_bytes = path.stat().st_size
        self.last_backup_error = None


def start_backup(pusher: _Pusher) -> BackupLoop | None:
    if not settings.backup_dir:
        return None
    loop = BackupLoop(
        Path(settings.db_path),
        Path(settings.backup_dir),
        settings.backup_at,
        _WallClock(),
        pusher,
    )
    loop.start()
    return loop


def health() -> dict[str, int | str | None] | None:
    if not settings.backup_dir:
        return None
    loop = _active
    if loop is None:
        return {"last_backup_at": None, "last_backup_bytes": None, "last_backup_error": None}
    return {
        "last_backup_at": loop.last_backup_at,
        "last_backup_bytes": loop.last_backup_bytes,
        "last_backup_error": loop.last_backup_error,
    }


def main() -> None:
    if not settings.backup_dir:
        raise SystemExit("BACKUP_DIR is empty")
    path = take_backup(
        Path(settings.db_path),
        Path(settings.backup_dir),
        now=datetime.now(UTC),
    )
    print(path)


if __name__ == "__main__":
    main()
