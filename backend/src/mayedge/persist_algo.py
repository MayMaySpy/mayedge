"""Chase-iceberg algo SQLite persistence."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from decimal import Decimal
from typing import Any

from mayedge.db import _connect, _lock
from mayedge.numbers import fmt_decimal

logger = logging.getLogger(__name__)


def upsert_run(
    snapshot: dict[str, Any],
    *,
    next_clip: int,
    next_fill: int,
    trade_ids: set[int],
    trade_qty_by_clip: dict[int, str],
    clips: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    archived: bool = False,
) -> None:
    algo_id = snapshot.get("algo_id")
    if not algo_id:
        return
    updated_at = int(time.time() * 1000)
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO algo_runs(
                algo_id, venue, algo_type, params_json, status, market_index, symbol, reduce_only,
                side, qty, display_qty, offset_bps, price_floor, price_ceiling,
                remaining, filled, quote_action, reason, rest_price, rest_qty,
                error, created_at, updated_at, archived, next_clip, next_fill,
                trade_qty_by_clip
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?
            )
            ON CONFLICT(algo_id) DO UPDATE SET
                venue=excluded.venue,
                algo_type=excluded.algo_type,
                params_json=excluded.params_json,
                status=excluded.status,
                market_index=excluded.market_index,
                symbol=excluded.symbol,
                reduce_only=excluded.reduce_only,
                side=excluded.side,
                qty=excluded.qty,
                display_qty=excluded.display_qty,
                offset_bps=excluded.offset_bps,
                price_floor=excluded.price_floor,
                price_ceiling=excluded.price_ceiling,
                remaining=excluded.remaining,
                filled=excluded.filled,
                quote_action=excluded.quote_action,
                reason=excluded.reason,
                rest_price=excluded.rest_price,
                rest_qty=excluded.rest_qty,
                error=excluded.error,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                archived=excluded.archived,
                next_clip=excluded.next_clip,
                next_fill=excluded.next_fill,
                trade_qty_by_clip=excluded.trade_qty_by_clip
            """,
            (
                algo_id,
                snapshot.get("venue") or "lighter",
                snapshot.get("algo_type") or snapshot.get("id") or "chase-iceberg",
                json.dumps(snapshot.get("params_json") or {}),
                snapshot.get("status") or "stopped",
                int(snapshot.get("market_index") or 0),
                snapshot.get("symbol") or "",
                1 if snapshot.get("reduce_only") else 0,
                snapshot.get("side"),
                snapshot.get("qty"),
                snapshot.get("display_qty"),
                snapshot.get("offset_bps"),
                snapshot.get("price_floor"),
                snapshot.get("price_ceiling"),
                snapshot.get("remaining"),
                snapshot.get("filled"),
                snapshot.get("quote_action"),
                snapshot.get("reason"),
                snapshot.get("rest_price"),
                snapshot.get("rest_qty"),
                snapshot.get("error"),
                int(snapshot.get("created_at") or 0),
                updated_at,
                1 if archived else 0,
                next_clip,
                next_fill,
                json.dumps(trade_qty_by_clip),
            ),
        )
        conn.execute("DELETE FROM algo_clips WHERE algo_id = ?", (algo_id,))
        conn.execute("DELETE FROM algo_fills WHERE algo_id = ?", (algo_id,))
        conn.execute("DELETE FROM algo_trade_ids WHERE algo_id = ?", (algo_id,))
        for c in clips:
            conn.execute(
                """
                INSERT INTO algo_clips(
                    algo_id, seq, client_order_index, order_index, side, price, qty, filled,
                    status, seen_on_book, placed_at, closed_at, missing_since
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    algo_id,
                    int(c["seq"]),
                    int(c["client_order_index"]),
                    int(c["order_index"]) if c.get("order_index") is not None else None,
                    c.get("side"),
                    str(c["price"]),
                    str(c["qty"]),
                    str(c.get("filled") or "0"),
                    str(c["status"]),
                    1 if c.get("seen_on_book") else 0,
                    int(c.get("placed_at") or 0),
                    int(c["closed_at"]) if c.get("closed_at") is not None else None,
                    int(c["missing_since"]) if c.get("missing_since") is not None else None,
                ),
            )
        for f in fills:
            conn.execute(
                """
                INSERT INTO algo_fills(
                    algo_id, seq, clip_seq, price, qty, ts, order_index, client_order_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    algo_id,
                    int(f["seq"]),
                    int(f["clip_seq"]),
                    str(f["price"]),
                    str(f["qty"]),
                    int(f["ts"]),
                    int(f["order_index"]) if f.get("order_index") is not None else None,
                    int(f["client_order_index"])
                    if f.get("client_order_index") is not None
                    else None,
                ),
            )
        for tid in trade_ids:
            conn.execute(
                "INSERT INTO algo_trade_ids(algo_id, trade_id) VALUES (?, ?)",
                (algo_id, int(tid)),
            )
        conn.commit()


def _row_to_run(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    algo_id = row["algo_id"]
    clips = [
        {
            "seq": r["seq"],
            "client_order_index": r["client_order_index"],
            "order_index": r["order_index"],
            "side": r["side"] if "side" in r.keys() else None,
            "price": r["price"],
            "qty": r["qty"],
            "filled": r["filled"],
            "status": r["status"],
            "seen_on_book": bool(r["seen_on_book"]),
            "placed_at": r["placed_at"],
            "closed_at": r["closed_at"],
            "missing_since": r["missing_since"],
        }
        for r in conn.execute("SELECT * FROM algo_clips WHERE algo_id = ? ORDER BY seq", (algo_id,))
    ]
    fills = [
        {
            "seq": r["seq"],
            "clip_seq": r["clip_seq"],
            "price": r["price"],
            "qty": r["qty"],
            "ts": r["ts"],
            "order_index": r["order_index"],
            "client_order_index": r["client_order_index"],
        }
        for r in conn.execute("SELECT * FROM algo_fills WHERE algo_id = ? ORDER BY seq", (algo_id,))
    ]
    trade_ids = {
        int(r["trade_id"])
        for r in conn.execute("SELECT trade_id FROM algo_trade_ids WHERE algo_id = ?", (algo_id,))
    }
    try:
        tq_raw = json.loads(row["trade_qty_by_clip"] or "{}")
    except json.JSONDecodeError:
        tq_raw = {}
    trade_qty_by_clip = {int(k): str(v) for k, v in tq_raw.items()}
    return {
        "algo_id": algo_id,
        "venue": row["venue"] if "venue" in dict(row) else "lighter",
        "algo_type": row["algo_type"] if "algo_type" in dict(row) else "chase-iceberg",
        "params_json": json.loads(row["params_json"] or "{}")
        if "params_json" in dict(row)
        else {},
        "status": row["status"],
        "market_index": row["market_index"],
        "symbol": row["symbol"],
        "reduce_only": bool(row["reduce_only"]),
        "side": row["side"],
        "qty": row["qty"],
        "display_qty": row["display_qty"],
        "offset_bps": row["offset_bps"],
        "price_floor": row["price_floor"],
        "price_ceiling": row["price_ceiling"],
        "remaining": row["remaining"],
        "filled": row["filled"],
        "quote_action": row["quote_action"],
        "reason": row["reason"],
        "rest_price": row["rest_price"],
        "rest_qty": row["rest_qty"],
        "error": row["error"],
        "created_at": row["created_at"],
        "archived": bool(row["archived"]),
        "next_clip": row["next_clip"],
        "next_fill": row["next_fill"],
        "clips": clips,
        "fills": fills,
        "trade_ids": trade_ids,
        "trade_qty_by_clip": trade_qty_by_clip,
    }


def load_active_runs(*, algo_type: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        clauses = ["archived = 0", "status IN ('running', 'paused', 'error')"]
        args: list[Any] = []
        if algo_type:
            clauses.append("algo_type = ?")
            args.append(algo_type)
        sql = f"SELECT * FROM algo_runs WHERE {' AND '.join(clauses)} ORDER BY created_at ASC"
        rows = conn.execute(sql, args).fetchall()
        return [_row_to_run(conn, r) for r in rows]


def load_history(limit: int = 30, *, algo_type: str | None = None) -> list[dict[str, Any]]:
    """Terminal snapshots shaped like ChaseIcebergRunner.snapshot()."""
    with _lock:
        conn = _connect()
        clauses = ["(archived = 1 OR status IN ('stopped', 'done'))"]
        args: list[Any] = []
        if algo_type:
            clauses.append("algo_type = ?")
            args.append(algo_type)
        args.append(limit)
        sql = f"""
            SELECT * FROM algo_runs
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC
            LIMIT ?
        """
        rows = conn.execute(sql, args).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            raw = _row_to_run(conn, r)
            out.append(_public_snapshot(raw))
        return out


def _public_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    from mayedge.algos.chase import ALGO_ID as CHASE_ID
    from mayedge.algos.chase import ALGO_VERSION as CHASE_VER

    algo_type = str(raw.get("algo_type") or CHASE_ID)
    pub_id, version = CHASE_ID, CHASE_VER

    clips = []
    for c in raw["clips"]:
        qty_d = Decimal(str(c["qty"]))
        filled_d = Decimal(str(c.get("filled") or "0"))
        rem = max(Decimal("0"), qty_d - filled_d)
        clips.append(
            {
                "seq": c["seq"],
                "client_order_index": str(c["client_order_index"]),
                "order_index": str(c["order_index"]) if c.get("order_index") is not None else None,
                "side": c.get("side"),
                "price": c["price"],
                "qty": c["qty"],
                "filled": c.get("filled") or "0",
                "remaining": fmt_decimal(rem) or "0",
                "status": c["status"],
                "placed_at": c["placed_at"],
                "closed_at": c.get("closed_at"),
            }
        )
    fills = [
        {
            "seq": f["seq"],
            "clip_seq": f["clip_seq"],
            "price": f["price"],
            "qty": f["qty"],
            "ts": f["ts"],
            "order_index": str(f["order_index"]) if f.get("order_index") is not None else None,
            "client_order_index": (
                str(f["client_order_index"]) if f.get("client_order_index") is not None else None
            ),
        }
        for f in raw["fills"]
    ]
    working = None
    working_bid = None
    working_ask = None
    for c in reversed(clips):
        if c["status"] == "live":
            if c.get("side") == "buy" and working_bid is None:
                working_bid = c
            elif c.get("side") == "sell" and working_ask is None:
                working_ask = c
            if working is None:
                working = c
    return {
        "type": "algo",
        "id": pub_id,
        "algo_type": algo_type,
        "version": version,
        "algo_id": raw["algo_id"],
        "status": raw["status"],
        "market_index": raw["market_index"],
        "symbol": raw["symbol"],
        "reduce_only": raw["reduce_only"],
        "side": raw["side"],
        "qty": raw["qty"],
        "display_qty": raw["display_qty"],
        "offset_bps": raw["offset_bps"],
        "price_floor": raw["price_floor"],
        "price_ceiling": raw["price_ceiling"],
        "remaining": raw["remaining"],
        "filled": raw["filled"],
        "quote_action": raw["quote_action"],
        "reason": raw["reason"],
        "rest_price": raw["rest_price"],
        "rest_qty": raw["rest_qty"],
        "rest_bid_price": working_bid["price"] if working_bid else None,
        "rest_bid_qty": working_bid["remaining"] if working_bid else None,
        "rest_ask_price": working_ask["price"] if working_ask else None,
        "rest_ask_qty": working_ask["remaining"] if working_ask else None,
        "working_coi": int(working["client_order_index"]) if working else None,
        "working_order_index": working["order_index"] if working else None,
        "error": raw["error"],
        "created_at": raw["created_at"] or None,
        "clips": clips,
        "fills": fills,
        "working": working,
        "working_bid": working_bid,
        "working_ask": working_ask,
    }
