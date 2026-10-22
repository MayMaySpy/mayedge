"""Price alert rows. A fire and its Idea log line commit together. Rules: docs/idea-rules.md A1–A11."""

from __future__ import annotations

import json
import sqlite3
import time
from decimal import Decimal
from typing import Any

from mayedge.db import _connect, _lock, reading
from mayedge.idea_alerts import (
    MAX_PER_IDEA,
    Alert,
    AlertSpec,
    Armed,
    arm,
    plan_levels,
    rearm_now,
)
from mayedge.ideas import OPEN, Refusal
from mayedge.numbers import parse_decimal


class Missing(Exception):
    """No such Idea, or no such alert."""


def alerts_for(idea_id: str) -> list[dict[str, Any]]:
    with reading() as conn:
        rows = conn.execute(
            "SELECT * FROM idea_alerts WHERE idea_id = ? ORDER BY id DESC", (idea_id,)
        ).fetchall()
    return [_public(row) for row in rows]


def alert_symbol(alert_id: int) -> str | None:
    """The Market an alert watches, through its Idea."""
    with reading() as conn:
        row = conn.execute(
            "SELECT i.symbol FROM idea_alerts a JOIN ideas i ON i.id = a.idea_id WHERE a.id = ?",
            (alert_id,),
        ).fetchone()
    return None if row is None else str(row[0])


def alert_add(
    idea_id: str,
    spec: AlertSpec,
    last: Decimal | None,
    change: Decimal | None,
    now: int | None = None,
) -> dict[str, Any]:
    """A1–A4. Raises Missing for no Idea, Refusal for a rule."""
    stamp = _now() if now is None else now
    armed = arm(spec, last, change)
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            _idea_row(conn, idea_id)
            if _count(conn, idea_id) >= MAX_PER_IDEA:
                raise Refusal("kind", f"An Idea holds at most {MAX_PER_IDEA} alerts.")
            alert_id = _insert(conn, idea_id, spec, armed, stamp)
            row = _must(conn, alert_id)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return _public(row)


def alerts_from_plan(
    idea_id: str, last: Decimal | None, now: int | None = None
) -> list[dict[str, Any]]:
    """A10. Once Level alerts on the Plan's prices that are not watched yet."""
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            idea = _idea_row(conn, idea_id)
            watched = {
                parse_decimal(str(row["price"]))
                for row in conn.execute(
                    "SELECT price FROM idea_alerts WHERE idea_id = ? AND kind = 'level' "
                    "AND status = 'armed' AND price IS NOT NULL",
                    (idea_id,),
                )
            }
            targets = [
                str(item.get("price"))
                for item in _json_list(idea["targets"])
                if isinstance(item, dict) and item.get("price")
            ]
            levels = plan_levels(
                _opt(idea["entry_low"]),
                _opt(idea["entry_high"]),
                _opt(idea["stop"]),
                targets,
                last,
                watched,
            )
            room = MAX_PER_IDEA - _count(conn, idea_id)
            if len(levels) > room:
                raise Refusal("kind", f"An Idea holds at most {MAX_PER_IDEA} alerts.")
            made: list[int] = []
            for price, label in levels:
                spec = AlertSpec("level", None, price, None, False, "", label)
                made.append(_insert(conn, idea_id, spec, arm(spec, last, None), stamp))
            rows = [_must(conn, alert_id) for alert_id in made]
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return [_public(row) for row in rows]


def alert_rearm(
    alert_id: int,
    last: Decimal | None,
    change: Decimal | None,
    now: int | None = None,
) -> dict[str, Any]:
    """A8: arm again as if new. Raises Refusal while Last cannot arm it."""
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _must(conn, alert_id)
            armed = rearm_now(_alert(row, ""), last, change)
            if armed is None:
                raise Refusal("status", _not_now(str(row["kind"])))
            _set_armed(conn, alert_id, armed, stamp)
            row = _must(conn, alert_id)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return _public(row)


def alert_delete(alert_id: int) -> None:
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute("DELETE FROM idea_alerts WHERE id = ?", (alert_id,))
            if cur.rowcount == 0:
                raise Missing
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def alerts_watched() -> list[Alert]:
    """A6: armed alerts, and fired Repeat ones, on Watching or Active Ideas."""
    marks = ",".join("?" for _ in OPEN)
    with reading() as conn:
        rows = conn.execute(
            f"""
            SELECT a.*, i.symbol AS symbol FROM idea_alerts a JOIN ideas i ON i.id = a.idea_id
            WHERE i.status IN ({marks}) AND (a.status = 'armed' OR (a.status = 'fired' AND a.repeat = 1))
            ORDER BY a.id
            """,
            OPEN,
        ).fetchall()
    return [_alert(row, str(row["symbol"])) for row in rows]


def alert_fire(alert_id: int, last: str | None, line: str, now: int | None = None) -> int | None:
    """A9: mark fired and log, in one transaction. The fire count, or None if it was not armed."""
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM idea_alerts WHERE id = ?", (alert_id,)).fetchone()
            if row is None or str(row["status"]) != "armed":
                conn.rollback()
                return None
            fires = int(row["fires"]) + 1
            conn.execute(
                "UPDATE idea_alerts SET status = 'fired', fires = ?, fired_at = ?, fired_last = ? "
                "WHERE id = ?",
                (fires, stamp, last, alert_id),
            )
            conn.execute(
                "INSERT INTO idea_log (idea_id, ts, kind, body, last) VALUES (?, ?, 'alert', ?, ?)",
                (str(row["idea_id"]), stamp, line, last),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return fires


def alert_auto_rearm(alert_id: int, armed: Armed, now: int | None = None) -> bool:
    """A8 for Repeat. Only a fired Repeat alert moves; anything else is left alone."""
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM idea_alerts WHERE id = ?", (alert_id,)).fetchone()
            if row is None or str(row["status"]) != "fired" or not int(row["repeat"]):
                conn.rollback()
                return False
            _set_armed(conn, alert_id, armed, stamp)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return True


def _insert(
    conn: sqlite3.Connection, idea_id: str, spec: AlertSpec, armed: Armed, stamp: int
) -> int:
    cur = conn.execute(
        """
        INSERT INTO idea_alerts (
            idea_id, kind, direction, price, pct, base, repeat, label, note, status, fires,
            created_at, armed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'armed', 0, ?, ?)
        """,
        (
            idea_id,
            spec.kind,
            armed.direction,
            spec.price,
            spec.pct,
            armed.base,
            1 if spec.repeat else 0,
            spec.label,
            spec.note,
            stamp,
            stamp,
        ),
    )
    return int(cur.lastrowid or 0)


def _set_armed(conn: sqlite3.Connection, alert_id: int, armed: Armed, stamp: int) -> None:
    conn.execute(
        "UPDATE idea_alerts SET status = 'armed', direction = ?, base = ?, armed_at = ? WHERE id = ?",
        (armed.direction, armed.base, stamp, alert_id),
    )


def _not_now(kind: str) -> str:
    if kind == "day":
        return (
            "Daily Change is still past this alert, or unknown. Try again once it is back inside."
        )
    if kind == "level":
        return "Last is on this price, or unknown. Try again once it moves."
    return "No Last for this Market yet."


def _idea_row(conn: sqlite3.Connection, idea_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if row is None:
        raise Missing
    return row


def _count(conn: sqlite3.Connection, idea_id: str) -> int:
    row = conn.execute("SELECT COUNT(*) FROM idea_alerts WHERE idea_id = ?", (idea_id,)).fetchone()
    return int(row[0]) if row else 0


def _must(conn: sqlite3.Connection, alert_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM idea_alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise Missing
    return row


def _alert(row: sqlite3.Row, symbol: str) -> Alert:
    return Alert(
        id=int(row["id"]),
        idea_id=str(row["idea_id"]),
        symbol=symbol,
        kind=str(row["kind"]),
        direction=str(row["direction"]),
        price=_opt(row["price"]),
        pct=_opt(row["pct"]),
        base=_opt(row["base"]),
        repeat=bool(int(row["repeat"])),
        label=str(row["label"] or ""),
        note=str(row["note"] or ""),
        status=str(row["status"]),
        fires=int(row["fires"]),
        armed_at=int(row["armed_at"]),
        fired_at=_opt_int(row["fired_at"]),
    )


def _public(row: sqlite3.Row) -> dict[str, Any]:
    alert = _alert(row, "")
    return {
        "id": alert.id,
        "idea_id": alert.idea_id,
        "kind": alert.kind,
        "direction": alert.direction,
        "price": alert.price,
        "pct": alert.pct,
        "base": alert.base,
        "repeat": alert.repeat,
        "label": alert.label,
        "note": alert.note,
        "status": alert.status,
        "fires": alert.fires,
        "created_at": int(row["created_at"]),
        "armed_at": alert.armed_at,
        "fired_at": alert.fired_at,
        "fired_last": _opt(row["fired_last"]),
    }


def _json_list(raw: object) -> list[Any]:
    try:
        value = json.loads(str(raw or "[]"))
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _opt(raw: object) -> str | None:
    return None if raw is None else str(raw)


def _opt_int(raw: object) -> int | None:
    return None if raw is None else int(str(raw))


def _now() -> int:
    return time.time_ns() // 1_000_000
