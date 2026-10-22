"""Idea rows. A Plan change and a status move log in the same transaction. Rules: docs/idea-rules.md."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from typing import Any

from mayedge.db import _connect, _lock, reading
from mayedge.ideas import (
    STATUSES,
    Clash,
    Idea,
    Refusal,
    algo_text,
    blank_plan,
    computed,
    log_text,
    move,
    normalise,
    outcome_of,
    plan_diff,
    planner_line,
    second_open,
    status_line,
)

_FIELDS = (
    "symbol",
    "side",
    "thesis",
    "conviction",
    "horizon",
    "invalidation",
    "trigger",
    "tags",
    "catalysts",
    "entry_low",
    "entry_high",
    "stop",
    "targets",
)


class Missing(Exception):
    """No row with that id."""


class Stale(Exception):
    """seen_updated_at is older than the row."""


class NotAllowed(Exception):
    """S2 does not allow the move."""


def ideas_list(status: str | None) -> list[dict[str, Any]]:
    where, args = _where(status)
    with reading() as conn:
        rows = conn.execute(
            f"SELECT * FROM ideas {where} ORDER BY updated_at DESC, id DESC",
            args,
        ).fetchall()
    return [_public(row) for row in rows]


def idea_get(idea_id: str) -> dict[str, Any] | None:
    with reading() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            return None
        log = _log(conn, idea_id)
    return {"idea": _public(row), "log": log}


def idea_insert(
    idea: Idea, last: str | None, now: int | None = None
) -> tuple[dict[str, Any], dict[str, str] | None]:
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            clash = _clash(conn, idea.symbol, idea.side)
            idea_id = _mint(conn)
            _put(conn, idea_id, idea, "watching", [], None, "", stamp, stamp, None)
            diff = plan_diff(blank_plan(idea), idea)
            if diff:
                _line(conn, idea_id, stamp, "plan", diff, last)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    warning = None if clash is None else _warning(clash)
    return _pack(idea_id, idea, "watching", [], None, "", stamp, stamp, None), warning


def idea_update(
    idea_id: str,
    fields: dict[str, Any],
    seen: int,
    last: str | None,
    now: int | None = None,
) -> dict[str, Any]:
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _must(conn, idea_id)
            if int(row["updated_at"]) > seen:
                raise Stale
            got = normalise(_merge(row, fields))
            if isinstance(got, Refusal):
                raise got
            diff = plan_diff(_idea(row), got)
            _put(
                conn,
                idea_id,
                got,
                str(row["status"]),
                _id_list(row["planner_ids"]),
                _opt(row["outcome"]),
                str(row["review"] or ""),
                int(row["created_at"]),
                stamp,
                _opt_int(row["closed_at"]),
            )
            if diff:
                _line(conn, idea_id, stamp, "plan", diff, last)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return _pack(
        idea_id,
        got,
        str(row["status"]),
        _id_list(row["planner_ids"]),
        _opt(row["outcome"]),
        str(row["review"] or ""),
        int(row["created_at"]),
        stamp,
        _opt_int(row["closed_at"]),
    )


def idea_status(
    idea_id: str,
    status: str,
    outcome: str | None,
    review: str | None,
    last: str | None,
    now: int | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise NotAllowed
    checked = outcome_of(outcome)
    if (checked is not None or (review is not None and review.strip() != "")) and status not in (
        "closed",
        "dropped",
    ):
        raise Refusal("outcome", "A Review is written when an Idea is Closed or Dropped.")
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _must(conn, idea_id)
            current = str(row["status"])
            if not move(current, status):
                raise NotAllowed
            idea = _idea(row)
            closed = int(row["closed_at"]) if row["closed_at"] is not None else None
            if status in ("closed", "dropped"):
                closed = stamp
            elif status == "watching":
                closed = None
            kept_outcome = checked if checked is not None else _opt(row["outcome"])
            kept_review = str(row["review"] or "") if review is None else review.strip()
            _put(
                conn,
                idea_id,
                idea,
                status,
                _id_list(row["planner_ids"]),
                kept_outcome,
                kept_review,
                int(row["created_at"]),
                stamp,
                closed,
            )
            _line(conn, idea_id, stamp, "status", status_line(current, status), last)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return _pack(
        idea_id,
        idea,
        status,
        _id_list(row["planner_ids"]),
        kept_outcome,
        kept_review,
        int(row["created_at"]),
        stamp,
        closed,
    )


def idea_review(
    idea_id: str,
    fields: dict[str, Any],
    now: int | None = None,
) -> dict[str, Any]:
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _must(conn, idea_id)
            idea = _idea(row)
            outcome = _opt(row["outcome"])
            review = str(row["review"] or "")
            if "outcome" in fields:
                outcome = outcome_of(fields["outcome"])
            if "review" in fields:
                text = fields["review"]
                if text is None:
                    review = ""
                elif not isinstance(text, str):
                    raise Refusal("review", "Type words.")
                else:
                    review = text.strip()
            _put(
                conn,
                idea_id,
                idea,
                str(row["status"]),
                _id_list(row["planner_ids"]),
                outcome,
                review,
                int(row["created_at"]),
                stamp,
                _opt_int(row["closed_at"]),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return _pack(
        idea_id,
        idea,
        str(row["status"]),
        _id_list(row["planner_ids"]),
        outcome,
        review,
        int(row["created_at"]),
        stamp,
        _opt_int(row["closed_at"]),
    )


def idea_log_add(
    idea_id: str,
    body: str,
    last: str | None,
    now: int | None = None,
) -> dict[str, Any]:
    text = log_text(body)
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            _must(conn, idea_id)
            conn.execute("UPDATE ideas SET updated_at = ? WHERE id = ?", (stamp, idea_id))
            line_id = _line(conn, idea_id, stamp, "update", text, last)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return {"id": line_id, "ts": stamp, "kind": "update", "body": text, "last": last}


def idea_planner(
    idea_id: str,
    algo_id: str,
    last: str | None,
    now: int | None = None,
) -> dict[str, Any]:
    algo = algo_text(algo_id)
    stamp = _now() if now is None else now
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _must(conn, idea_id)
            ids = _id_list(row["planner_ids"])
            if algo in ids:
                current = _public(row)
                conn.rollback()
                return current
            current_status = str(row["status"])
            if current_status == "watching":
                if not move(current_status, "active"):
                    raise NotAllowed
                status = "active"
            elif current_status == "active":
                status = "active"
            else:
                raise NotAllowed
            ids.append(algo)
            idea = _idea(row)
            _put(
                conn,
                idea_id,
                idea,
                status,
                ids,
                _opt(row["outcome"]),
                str(row["review"] or ""),
                int(row["created_at"]),
                stamp,
                _opt_int(row["closed_at"]),
            )
            _line(conn, idea_id, stamp, "planner", planner_line(current_status, status, algo), last)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return _pack(
        idea_id,
        idea,
        status,
        ids,
        _opt(row["outcome"]),
        str(row["review"] or ""),
        int(row["created_at"]),
        stamp,
        _opt_int(row["closed_at"]),
    )


def idea_delete(idea_id: str) -> None:
    with _lock:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
            if cur.rowcount == 0:
                raise Missing
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def _where(status: str | None) -> tuple[str, tuple[str, ...]]:
    if status in (None, "", "open"):
        return "WHERE status IN ('watching', 'active')", ()
    if status == "all":
        return "", ()
    if status in STATUSES:
        return "WHERE status = ?", (status,)
    raise ValueError(status)


def _clash(conn: sqlite3.Connection, symbol: str, side: str) -> Clash | None:
    rows = conn.execute(
        "SELECT id, symbol, side FROM ideas WHERE status IN ('watching', 'active') "
        "ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    return second_open(
        [Clash(str(row["id"]), str(row["symbol"]), str(row["side"])) for row in rows],
        symbol,
        side,
    )


def _warning(clash: Clash) -> dict[str, str]:
    return {
        "id": clash.id,
        "message": f"You already have an open {clash.symbol} {clash.side}.",
    }


def _mint(conn: sqlite3.Connection) -> str:
    for _ in range(5):
        idea_id = "idea-" + secrets.token_hex(6)
        if conn.execute("SELECT 1 FROM ideas WHERE id = ?", (idea_id,)).fetchone() is None:
            return idea_id
    raise RuntimeError("could not mint an idea id")


def _put(
    conn: sqlite3.Connection,
    idea_id: str,
    idea: Idea,
    status: str,
    planner_ids: list[str],
    outcome: str | None,
    review: str,
    created_at: int,
    updated_at: int,
    closed_at: int | None,
) -> None:
    conn.execute(
        """
        INSERT INTO ideas (
            id, symbol, side, status, conviction, horizon, thesis, invalidation, trigger,
            tags, catalysts, entry_low, entry_high, stop, targets, planner_ids,
            outcome, review, created_at, updated_at, closed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            symbol=excluded.symbol, side=excluded.side, status=excluded.status,
            conviction=excluded.conviction, horizon=excluded.horizon, thesis=excluded.thesis,
            invalidation=excluded.invalidation, trigger=excluded.trigger,
            tags=excluded.tags, catalysts=excluded.catalysts,
            entry_low=excluded.entry_low, entry_high=excluded.entry_high,
            stop=excluded.stop, targets=excluded.targets, planner_ids=excluded.planner_ids,
            outcome=excluded.outcome, review=excluded.review,
            updated_at=excluded.updated_at, closed_at=excluded.closed_at
        """,
        (
            idea_id,
            idea.symbol,
            idea.side,
            status,
            idea.conviction,
            idea.horizon,
            idea.thesis,
            idea.invalidation,
            idea.trigger,
            json.dumps(list(idea.tags), ensure_ascii=False),
            json.dumps(
                [{"text": item.text, "date": item.date} for item in idea.catalysts],
                ensure_ascii=False,
            ),
            idea.entry_low,
            idea.entry_high,
            idea.stop,
            json.dumps(
                [{"price": item.price, "pct": item.pct} for item in idea.targets],
                ensure_ascii=False,
            ),
            json.dumps(planner_ids, ensure_ascii=False),
            outcome,
            review,
            created_at,
            updated_at,
            closed_at,
        ),
    )


def _line(
    conn: sqlite3.Connection,
    idea_id: str,
    stamp: int,
    kind: str,
    body: str,
    last: str | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO idea_log (idea_id, ts, kind, body, last) VALUES (?, ?, ?, ?, ?)",
        (idea_id, stamp, kind, body, last),
    )
    return int(cur.lastrowid or 0)


def _log(conn: sqlite3.Connection, idea_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, ts, kind, body, last FROM idea_log WHERE idea_id = ? ORDER BY ts DESC, id DESC",
        (idea_id,),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "ts": int(row["ts"]),
            "kind": str(row["kind"]),
            "body": str(row["body"]),
            "last": _opt(row["last"]),
        }
        for row in rows
    ]


def _must(conn: sqlite3.Connection, idea_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if row is None:
        raise Missing
    return row


def _merge(row: sqlite3.Row, fields: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "symbol": str(row["symbol"]),
        "side": str(row["side"]),
        "thesis": str(row["thesis"]),
        "conviction": int(row["conviction"]),
        "horizon": str(row["horizon"]),
        "invalidation": str(row["invalidation"] or ""),
        "trigger": str(row["trigger"] or ""),
        "tags": _str_list(row["tags"]),
        "catalysts": _obj_list(row["catalysts"]),
        "entry_low": _opt(row["entry_low"]),
        "entry_high": _opt(row["entry_high"]),
        "stop": _opt(row["stop"]),
        "targets": _obj_list(row["targets"]),
    }
    for key in _FIELDS:
        if key in fields:
            body[key] = fields[key]
    return body


def _idea(row: sqlite3.Row) -> Idea:
    got = normalise(_merge(row, {}))
    if isinstance(got, Refusal):
        raise got
    return got


def _public(row: sqlite3.Row) -> dict[str, Any]:
    idea = _idea(row)
    return _pack(
        str(row["id"]),
        idea,
        str(row["status"]),
        _id_list(row["planner_ids"]),
        _opt(row["outcome"]),
        str(row["review"] or ""),
        int(row["created_at"]),
        int(row["updated_at"]),
        _opt_int(row["closed_at"]),
    )


def _pack(
    idea_id: str,
    idea: Idea,
    status: str,
    planner_ids: list[str],
    outcome: str | None,
    review: str,
    created_at: int,
    updated_at: int,
    closed_at: int | None,
) -> dict[str, Any]:
    return {
        "id": idea_id,
        "symbol": idea.symbol,
        "side": idea.side,
        "status": status,
        "conviction": idea.conviction,
        "horizon": idea.horizon,
        "thesis": idea.thesis,
        "invalidation": idea.invalidation,
        "trigger": idea.trigger,
        "tags": list(idea.tags),
        "catalysts": [{"text": item.text, "date": item.date} for item in idea.catalysts],
        "entry_low": idea.entry_low,
        "entry_high": idea.entry_high,
        "stop": idea.stop,
        "targets": [{"price": item.price, "pct": item.pct} for item in idea.targets],
        "planner_ids": planner_ids,
        "outcome": outcome,
        "review": review,
        "created_at": created_at,
        "updated_at": updated_at,
        "closed_at": closed_at,
        **computed(idea),
    }


def _str_list(raw: object) -> list[str]:
    return [str(item) for item in _json_list(raw) if isinstance(item, str)]


def _id_list(raw: object) -> list[str]:
    return _str_list(raw)


def _obj_list(raw: object) -> list[dict[str, Any]]:
    return [item for item in _json_list(raw) if isinstance(item, dict)]


def _json_list(raw: object) -> list[Any]:
    if not isinstance(raw, str):
        return []
    try:
        got = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return got if isinstance(got, list) else []


def _opt(raw: object) -> str | None:
    if raw is None:
        return None
    return str(raw)


def _opt_int(raw: object) -> int | None:
    if raw is None:
        return None
    return int(str(raw))


def _now() -> int:
    return time.time_ns() // 1_000_000
