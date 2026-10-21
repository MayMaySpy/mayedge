from __future__ import annotations

import asyncio
import gzip
import shutil
import sqlite3
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from mayedge import backup
from mayedge import db as store
from mayedge.api.app import create_app
from mayedge.backup import BackupLoop, take_backup
from mayedge.config import settings


def _utc(y: int, m: int, d: int, hh: int, mm: int) -> float:
    return datetime(y, m, d, hh, mm, tzinfo=UTC).timestamp()


class FakeClock:
    def __init__(self, t: float) -> None:
        self.t = t

    def now(self) -> float:
        return self.t

    def mono(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.t += seconds
        await asyncio.sleep(0)


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool]] = []

    def push(self, key: str, text: str, *, urgent: bool = False, force: bool = False) -> None:
        self.rows.append((key, text, urgent))


def _counts(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        return {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in names
        }
    finally:
        conn.close()


def _counts_gz(gz: Path) -> dict[str, int]:
    raw = gz.parent / "_opened.db"
    with gzip.open(gz, "rb") as src, raw.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    try:
        return _counts(raw)
    finally:
        raw.unlink(missing_ok=True)


class TakeBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        root = Path(self._td.name)
        self.db = root / "mayedge.db"
        self.dest = root / "backups"
        self._db = patch.object(settings, "db_path", str(self.db))
        self._keep = patch.object(settings, "backup_keep", 7)
        self._db.start()
        self._keep.start()
        store.close_db()
        store.init_db()
        with store._lock:
            conn = store._connect()
            conn.execute("INSERT INTO meta(key, value) VALUES('k', 'v')")
            conn.execute(
                "INSERT INTO journal_notes(trip_key, note, tags, updated_at) VALUES('t', 'n', '[]', 1)"
            )
            conn.execute(
                "INSERT INTO journal_funding(market_index, ts, amount) VALUES(1, 2, '3')"
            )
            conn.commit()
        backup._active = None

    def tearDown(self) -> None:
        store.close_db()
        self._keep.stop()
        self._db.stop()
        self._td.cleanup()
        backup._active = None

    def _now(self) -> datetime:
        return datetime(2026, 10, 21, 4, 0, tzinfo=UTC)

    def test_the_copy_has_the_same_row_count_in_every_table(self) -> None:
        path = take_backup(self.db, self.dest, now=self._now())
        self.assertEqual(_counts_gz(path), _counts(self.db))

    def test_the_file_name_is_the_utc_date_and_a_second_replaces_it(self) -> None:
        first = take_backup(self.db, self.dest, now=self._now())
        self.assertEqual(first.name, "mayedge-2026-10-21.db.gz")
        before = first.read_bytes()
        with store._lock:
            conn = store._connect()
            conn.execute("INSERT INTO meta(key, value) VALUES('k2', 'v2')")
            conn.commit()
        second = take_backup(self.db, self.dest, now=self._now())
        files = list(self.dest.glob("mayedge-*.db.gz"))
        self.assertEqual(files, [second])
        self.assertNotEqual(second.read_bytes(), before)

    def test_pruning_keeps_backup_keep_and_leaves_other_files(self) -> None:
        for day in ("2026-10-18", "2026-10-19", "2026-10-20"):
            self.dest.mkdir(exist_ok=True)
            (self.dest / f"mayedge-{day}.db.gz").write_bytes(b"old")
        (self.dest / "notes.txt").write_bytes(b"keep")
        (self.dest / "mayedge-not-a-backup.txt").write_bytes(b"keep")
        with patch.object(settings, "backup_keep", 2):
            take_backup(self.db, self.dest, now=self._now())
        names = sorted(p.name for p in self.dest.iterdir())
        self.assertEqual(
            names,
            [
                "mayedge-2026-10-20.db.gz",
                "mayedge-2026-10-21.db.gz",
                "mayedge-not-a-backup.txt",
                "notes.txt",
            ],
        )

    def test_take_backup_does_not_acquire_the_writer_lock(self) -> None:
        err: list[BaseException] = []

        def run() -> None:
            try:
                take_backup(self.db, self.dest, now=self._now())
            except BaseException as exc:
                err.append(exc)

        worker = threading.Thread(target=run)
        store._lock.acquire()
        worker.start()
        worker.join(2)
        blocked = worker.is_alive()
        store._lock.release()
        worker.join(5)
        self.assertFalse(blocked)
        self.assertEqual(err, [])
        self.assertTrue((self.dest / "mayedge-2026-10-21.db.gz").is_file())


class QuickCheckTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._td = TemporaryDirectory()
        root = Path(self._td.name)
        self.db = root / "mayedge.db"
        self.dest = root / "backups"
        self._db = patch.object(settings, "db_path", str(self.db))
        self._db.start()
        store.close_db()
        store.init_db()
        backup._active = None

    def tearDown(self) -> None:
        store.close_db()
        self._db.stop()
        self._td.cleanup()
        backup._active = None

    async def test_a_failed_quick_check_leaves_no_file_and_records_the_error(self) -> None:
        loop = BackupLoop(self.db, self.dest, "03:30", FakeClock(_utc(2026, 10, 21, 4, 0)))

        def boom(_path: Path) -> None:
            raise RuntimeError("not ok")

        with (
            patch("mayedge.backup._quick_check", boom),
            self.assertLogs("mayedge.backup", level="ERROR"),
        ):
            await loop.run_once()
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertEqual(loop.last_backup_error, "not ok")


class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def _until(self, pred) -> None:
        for _ in range(40):
            if pred():
                return
            await asyncio.sleep(0)
        self.fail("loop did not fire")

    async def test_it_fires_ten_minutes_after_boot_then_at_backup_at(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            takes: list[datetime] = []

            def take(_db: Path, folder: Path, *, now: datetime) -> Path:
                takes.append(now)
                path = folder / f"mayedge-{now:%Y-%m-%d}.db.gz"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"1")
                return path

            clock = FakeClock(_utc(2026, 10, 21, 3, 0))
            loop = BackupLoop(Path("db"), dest, "03:30", clock, take=take)
            task = asyncio.create_task(loop.run())
            await self._until(lambda: len(takes) >= 2)
            task.cancel()
            await loop.stop()
            self.assertEqual(takes[0], datetime(2026, 10, 21, 3, 10, tzinfo=UTC))
            self.assertEqual(takes[1], datetime(2026, 10, 21, 3, 30, tzinfo=UTC))

    async def test_it_skips_the_boot_backup_when_today_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / "mayedge-2026-10-21.db.gz").write_bytes(b"old")
            takes: list[datetime] = []

            def take(_db: Path, folder: Path, *, now: datetime) -> Path:
                takes.append(now)
                path = folder / f"mayedge-{now:%Y-%m-%d}.db.gz"
                path.write_bytes(b"new")
                return path

            clock = FakeClock(_utc(2026, 10, 21, 3, 0))
            loop = BackupLoop(Path("db"), dest, "03:30", clock, take=take)
            task = asyncio.create_task(loop.run())
            await self._until(lambda: len(takes) >= 1)
            task.cancel()
            await loop.stop()
            self.assertEqual(takes[0], datetime(2026, 10, 21, 3, 30, tzinfo=UTC))

    async def test_a_failure_pushes_once_and_the_loop_keeps_running(self) -> None:
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            sink = Sink()
            calls = {"n": 0}

            def take(db_path: Path, dest_dir: Path, *, now: datetime) -> Path:
                del db_path
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("disk full")
                path = dest_dir / f"mayedge-{now:%Y-%m-%d}.db.gz"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"1")
                return path

            clock = FakeClock(_utc(2026, 10, 21, 3, 0))
            loop = BackupLoop(Path("db"), dest, "03:30", clock, sink, take=take)
            task = asyncio.create_task(loop.run())
            with self.assertLogs("mayedge.backup", level="ERROR"):
                await self._until(lambda: calls["n"] >= 2 and loop.last_backup_at is not None)
            self.assertFalse(task.done())
            task.cancel()
            await loop.stop()
            self.assertEqual(sink.rows, [("backup", "⚠️ Backup failed: disk full", False)])
            self.assertIsNone(loop.last_backup_error)


class HealthTests(unittest.IsolatedAsyncioTestCase):
    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    async def test_an_empty_dir_starts_nothing_and_health_is_null(self, *_mocks: object) -> None:
        backup._active = None
        with patch.object(settings, "backup_dir", ""):
            app = create_app()
            transport = ASGITransport(app=app)
            async with (
                app.router.lifespan_context(app),
                AsyncClient(transport=transport, base_url="http://localhost") as client,
            ):
                body = (await client.get("/api/health")).json()
                started = app.state.backup
        self.assertIsNone(body["backup"])
        self.assertIsNone(started)
