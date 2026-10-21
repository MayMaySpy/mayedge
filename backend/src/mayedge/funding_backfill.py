"""Backfill settled funding from Lighter's /api/v1/fundings: hourly prints, then days.

The venue does not document the units of a funding row, so the desk does not assume
them. It reads the venue's latest rows against the prints it recorded live, keeps the
one reading that matches, and writes nothing if no single reading fits. The venue keeps
about 62 days of hours; its daily rows are checked against days rebuilt from those
hours before any older day is written.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from itertools import product
from typing import Any

from mayedge import db as store
from mayedge.persist_funding import FUNDING_DAY_S, FUNDING_HOUR_S, HOURS_PER_DAY

logger = logging.getLogger(__name__)

FUNDING_PAGE = 750
BACKFILL_DAYS = 365
CALIBRATION_MARKETS = 8
CALIBRATION_MIN_MATCHES = 3
DAY_PAGE = 400
DAY_PROBE = 60

# (market_index, end_ms, count, resolution) -> raw funding rows, newest window ending at end_ms.
FetchFundings = Callable[[int, int, int, str], Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True)
class VenueFunding:
    time_s: int
    rate: float
    direction: str


@dataclass(frozen=True)
class Reading:
    """How a venue row maps to a desk print."""

    shift: int  # hour_index = time_s // 3600 + shift
    scale: float  # venue rate * scale = desk percent
    sign: str  # "direction": long pays is +; "inverse": short is +; "as_is": rate is signed

    def hour(self, row: VenueFunding) -> int:
        return row.time_s // FUNDING_HOUR_S + self.shift

    def rate(self, row: VenueFunding) -> float:
        value = row.rate * self.scale
        if self.sign == "as_is":
            return value
        shorts_pay = row.direction.lower().startswith("short")
        if self.sign == "inverse":
            shorts_pay = not shorts_pay
        return -abs(value) if shorts_pay else abs(value)


READINGS: tuple[Reading, ...] = tuple(
    Reading(shift, scale, sign)
    for shift, scale, sign in product((-1, 0), (1.0, 100.0), ("direction", "inverse", "as_is"))
)


def parse_venue_fundings(raw: Iterable[Any]) -> list[VenueFunding]:
    """Rows with a time and a finite rate. Millisecond stamps are read as seconds."""
    out: list[VenueFunding] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            stamp = int(float(row["timestamp"]))
            rate = float(row["rate"])
        except (KeyError, TypeError, ValueError):
            continue
        if stamp > 10**12:
            stamp //= 1000
        if stamp <= 0 or not math.isfinite(rate):
            continue
        out.append(VenueFunding(stamp, rate, str(row.get("direction") or "")))
    return out


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-7, 1e-4 * abs(b))


def calibrate(samples: list[tuple[list[VenueFunding], dict[int, float]]]) -> Reading | None:
    """The reading under which every overlapping hour matches the desk's own prints.

    Several readings may fit when the data cannot tell them apart (every rate positive,
    say). That is fine only if they store the same values for every row seen.
    """
    fits: list[Reading] = []
    for reading in READINGS:
        matches = 0
        clean = True
        for rows, local in samples:
            for row in rows:
                mine = local.get(reading.hour(row))
                if mine is None:
                    continue
                if _same(reading.rate(row), mine):
                    matches += 1
                else:
                    clean = False
                    break
            if not clean:
                break
        if clean and matches >= CALIBRATION_MIN_MATCHES:
            fits.append(reading)
    if not fits:
        return None
    rows = [row for venue, _local in samples for row in venue]
    first = fits[0]
    for other in fits[1:]:
        for row in rows:
            if other.hour(row) != first.hour(row) or not _same(other.rate(row), first.rate(row)):
                return None
    return first


async def backfill_funding(
    perps: list[Any],
    fetch: FetchFundings,
    *,
    now: float,
    days: int = BACKFILL_DAYS,
) -> int:
    """Fill each perp's prints back `days`. Returns prints written. Perps are done once."""
    this_hour = int(now) // FUNDING_HOUR_S
    end_ms = int(now) * 1000
    local = store.recent_funding_prints(this_hour - 72)
    probes = [m for m in perps if local.get(int(m.market_index))][:CALIBRATION_MARKETS]
    samples: list[tuple[list[VenueFunding], dict[int, float]]] = []
    for meta in probes:
        idx = int(meta.market_index)
        rows = parse_venue_fundings(await fetch(idx, end_ms, 72, "1h"))
        samples.append((rows, local[idx]))
    reading = calibrate(samples)
    if reading is None:
        overlaps = sum(len(rows) for rows, _local in samples)
        logger.warning(
            "funding backfill skipped: no single reading matches the desk's prints "
            "(%d probe markets, %d venue rows)",
            len(samples),
            overlaps,
        )
        return 0
    logger.info("funding backfill reading %s", reading)
    oldest_wanted = this_hour - days * 24
    written = 0
    for meta in perps:
        idx = int(meta.market_index)
        if store.funding_backfill_done(idx):
            continue
        try:
            got, oldest = await _backfill_market(
                idx, fetch, reading, end_ms, oldest_wanted, this_hour
            )
        except Exception:
            logger.exception("funding backfill failed market=%s; retried next run", idx)
            continue
        written += got
        store.mark_funding_backfill_done(idx, oldest)
    logger.info("funding backfill wrote %d prints", written)
    return written


async def _backfill_market(
    idx: int,
    fetch: FetchFundings,
    reading: Reading,
    end_ms: int,
    oldest_wanted: int,
    this_hour: int,
) -> tuple[int, int | None]:
    """Page back from `end_ms` until the venue runs out or the window is covered."""
    cursor = end_ms
    oldest: int | None = None
    written = 0
    while True:
        rows = parse_venue_fundings(await fetch(idx, cursor, FUNDING_PAGE, "1h"))
        batch = [
            {"market_index": idx, "hour_index": reading.hour(row), "rate": reading.rate(row)}
            for row in rows
            if oldest_wanted <= reading.hour(row) < this_hour
        ]
        written += store.insert_missing_funding_prints(batch)
        if not rows:
            break
        earliest = min(row.time_s for row in rows)
        if oldest is not None and earliest * 1000 > cursor:
            break  # the venue ignored the cursor
        oldest = min(reading.hour(row) for row in rows)
        if oldest <= oldest_wanted or len(rows) < FUNDING_PAGE:
            break
        cursor = earliest * 1000 - 1
    return written, oldest


@dataclass(frozen=True)
class DayReading:
    """How a venue daily row maps to a desk Funding day (the day's mean 1h rate)."""

    shift: int  # day_index = time_s // 86400 + shift
    scale: float
    sign: str
    agg: str  # what the venue's day is: "mean" or "sum" of its hours, or its "last" hour

    def day(self, row: VenueFunding) -> int:
        return row.time_s // FUNDING_DAY_S + self.shift

    def value(self, row: VenueFunding) -> float:
        return Reading(0, self.scale, self.sign).rate(row)

    def mean(self, row: VenueFunding) -> float | None:
        """The day's mean 1h rate, or None when the venue's day cannot give it."""
        if self.agg == "mean":
            return self.value(row)
        if self.agg == "sum":
            return self.value(row) / HOURS_PER_DAY
        return None


DAY_READINGS: tuple[DayReading, ...] = tuple(
    DayReading(shift, scale, sign, agg)
    for shift, scale, sign, agg in product(
        (-1, 0), (1.0, 100.0), ("direction", "inverse", "as_is"), ("mean", "sum", "last")
    )
)


def full_days(prints: dict[int, float]) -> dict[int, dict[str, float]]:
    """Days with all 24 prints, as the venue might total them."""
    by_day: dict[int, list[tuple[int, float]]] = {}
    for hour, rate in prints.items():
        by_day.setdefault(hour // HOURS_PER_DAY, []).append((hour, rate))
    out: dict[int, dict[str, float]] = {}
    for day, rows in by_day.items():
        if len(rows) != HOURS_PER_DAY:
            continue
        rows.sort()
        total = sum(rate for _hour, rate in rows)
        out[day] = {"mean": total / HOURS_PER_DAY, "sum": total, "last": rows[-1][1]}
    return out


def _same_day(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-6, 1e-3 * abs(b))


def score_day_readings(
    samples: list[tuple[list[VenueFunding], dict[int, dict[str, float]]]],
) -> list[tuple[DayReading, int, int]]:
    """(reading, matches, misses) for every reading, best first."""
    scored: list[tuple[DayReading, int, int]] = []
    for reading in DAY_READINGS:
        matches = misses = 0
        for rows, days in samples:
            for row in rows:
                mine = days.get(reading.day(row))
                if mine is None:
                    continue
                if _same_day(reading.value(row), mine[reading.agg]):
                    matches += 1
                else:
                    misses += 1
        scored.append((reading, matches, misses))
    scored.sort(key=lambda item: (item[2], -item[1]))
    return scored


def calibrate_days(
    samples: list[tuple[list[VenueFunding], dict[int, dict[str, float]]]],
) -> DayReading | None:
    """The reading under which every overlapping full day matches, if only one stores values."""
    fits = [
        reading
        for reading, matches, misses in score_day_readings(samples)
        if misses == 0 and matches >= CALIBRATION_MIN_MATCHES
    ]
    if not fits:
        return None
    rows = [row for venue, _days in samples for row in venue]
    first = fits[0]
    for other in fits[1:]:
        for row in rows:
            a, b = first.mean(row), other.mean(row)
            if other.day(row) != first.day(row) or (a is None) != (b is None):
                return None
            if a is not None and b is not None and not _same_day(a, b):
                return None
    return first


def _day_text(day: int | None) -> str:
    if day is None:
        return "none"
    return time.strftime("%Y-%m-%d", time.gmtime(day * FUNDING_DAY_S))


async def backfill_funding_days(
    perps: list[Any],
    fetch: FetchFundings,
    *,
    now: float,
    days: int = BACKFILL_DAYS,
) -> int:
    """Fill each perp's Funding days back `days`. Returns days written. Perps are done once."""
    this_day = int(now) // FUNDING_DAY_S
    end_ms = int(now) * 1000
    since_hour = (this_day - DAY_PROBE) * HOURS_PER_DAY
    samples: list[tuple[list[VenueFunding], dict[int, dict[str, float]]]] = []
    for meta in perps:
        if len(samples) >= CALIBRATION_MARKETS:
            break
        idx = int(meta.market_index)
        local = full_days(store.funding_prints_for(idx, since_hour))
        if len(local) < CALIBRATION_MIN_MATCHES:
            continue
        rows = parse_venue_fundings(await fetch(idx, end_ms, DAY_PROBE, "1d"))
        samples.append((rows, local))
        logger.info(
            "funding days probe market=%s venue rows=%d oldest=%s",
            idx,
            len(rows),
            _day_text(min((row.time_s // FUNDING_DAY_S for row in rows), default=None)),
        )
    reading = calibrate_days(samples)
    if reading is None or reading.agg == "last":
        best = ", ".join(f"{r} {m} match {x} miss" for r, m, x in score_day_readings(samples)[:3])
        logger.warning(
            "funding days backfill skipped: %s (%d probe markets). Best readings: %s",
            "the venue's day is its last hour, not a mean" if reading else "no single reading fits",
            len(samples),
            best,
        )
        return 0
    logger.info("funding days backfill reading %s", reading)
    oldest_wanted = this_day - days
    written = 0
    oldest_seen: int | None = None
    for meta in perps:
        idx = int(meta.market_index)
        if store.funding_days_backfill_done(idx):
            continue
        try:
            rows = parse_venue_fundings(await fetch(idx, end_ms, DAY_PAGE, "1d"))
        except Exception:
            logger.exception("funding days backfill failed market=%s; retried next run", idx)
            continue
        batch: list[dict[str, Any]] = []
        for row in rows:
            day = reading.day(row)
            mean = reading.mean(row)
            if mean is None or not oldest_wanted <= day < this_day:
                continue
            batch.append({"market_index": idx, "day_index": day, "rate": mean})
        written += store.insert_funding_days(batch)
        oldest = min((row["day_index"] for row in batch), default=None)
        if oldest is not None:
            oldest_seen = oldest if oldest_seen is None else min(oldest_seen, oldest)
        store.mark_funding_days_backfill_done(idx, oldest)
    logger.info("funding days backfill wrote %d days, oldest %s", written, _day_text(oldest_seen))
    return written
