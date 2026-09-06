from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import lighter
import websockets

from mayedge import feed_health
from mayedge.config import settings
from mayedge.lighter.gateway import gateway
from mayedge.lighter.models import AccountSummary, OpenOrder, to_float
from mayedge.lighter.parse import (
    apply_orders,
    desk_account_trade,
    desk_position_funding,
    incoming_orders_by_market,
    iter_trade_rows,
    merge_account_assets,
    merge_positions,
    parse_order,
    parse_position,
)

logger = logging.getLogger(__name__)

_ACCOUNT_WS_TTL = 6 * 60
_PING_EVERY = 25.0
_SILENCE_S = 45.0
_REFRESH_DELAY = 0.2
_ACCOUNT_PUBLISH_MS = 0.15


class AccountService:
    """Live account cache via account_all_positions, orders, trades, assets, user_stats."""

    def __init__(self) -> None:
        self._ws_task: asyncio.Task[None] | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._refresh_wanted = False
        self._publish_task: asyncio.Task[None] | None = None
        self._publish_pending = False
        self._summary = AccountSummary(collateral="0", available="0", unrealized_pnl="0")
        self._orders_by_market: dict[int, list[OpenOrder]] = {}
        self._assets: Any = None
        self._auth_token_fn: Callable[[], Awaitable[str]] | None = None
        self._orders_hydrated = False

    def orders_hydrated(self) -> bool:
        return self._orders_hydrated

    def set_auth_token_fn(self, fn: Callable[[], Awaitable[str]] | None) -> None:
        self._auth_token_fn = fn

    async def start(self) -> None:
        if settings.lighter_account_index:
            try:
                self._summary = await self.fetch_account_summary()
                self._orders_by_market = self._index_orders(self._summary.open_orders)
                self._orders_hydrated = True
                self._publish()
            except Exception:
                logger.exception("account initial fetch failed")
            self._ws_task = asyncio.create_task(self._run_account_ws())

    async def stop(self) -> None:
        for task in (self._refresh_task, self._publish_task, self._ws_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._refresh_task = None
        self._publish_task = None
        self._ws_task = None

    @staticmethod
    def _index_orders(orders: list[OpenOrder]) -> dict[int, list[OpenOrder]]:
        by_market: dict[int, list[OpenOrder]] = {}
        for order in orders:
            by_market.setdefault(order.market_index, []).append(order)
        return by_market

    def _flatten_orders(self) -> list[OpenOrder]:
        out: list[OpenOrder] = []
        for rows in self._orders_by_market.values():
            out.extend(rows)
        return out

    def cached_account_payload(self) -> dict[str, Any] | None:
        payload = self._summary.to_public_dict()
        payload["type"] = "account"
        return payload

    def _remember_assets(self, incoming: Any) -> None:
        if not incoming:
            return
        self._assets = merge_account_assets(self._assets, incoming)

    def _resolve_trade_available(self, stats: dict[str, Any] | None, available: str) -> str:
        if isinstance(stats, dict):
            buying = stats.get("buying_power")
            if buying is not None and to_float(buying) > 0:
                return str(buying).strip()
        if self._assets and gateway.margin_asset_details():
            return gateway.trade_available_usd(available, self._assets)
        return available

    def _refresh_trade_available(self, stats: dict[str, Any] | None = None) -> None:
        self._summary.trade_available = self._resolve_trade_available(
            stats, self._summary.available
        )

    def _publish(self) -> None:
        self._publish_pending = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._emit_account()
            return
        task = self._publish_task
        if task is not None and not task.done():
            return
        self._publish_task = loop.create_task(self._flush_publish())

    async def _flush_publish(self) -> None:
        await asyncio.sleep(_ACCOUNT_PUBLISH_MS)
        while self._publish_pending:
            self._publish_pending = False
            self._emit_account()

    def _emit_account(self) -> None:
        for pos in self._summary.positions:
            meta = gateway.get_market_by_index(pos.market_index)
            mark = None
            if meta:
                mark = meta.mark_price or meta.last_trade_price
            if mark and mark > 0:
                pos.mark_price = str(mark)
                entry = to_float(pos.entry_price)
                size = to_float(pos.size)
                if entry > 0 and size != 0:
                    pos.unrealized_pnl = str((mark - entry) * size)
        self._summary.open_orders = self._flatten_orders()
        pnl = sum(to_float(pos.unrealized_pnl) for pos in self._summary.positions)
        self._summary.unrealized_pnl = str(pnl)
        self._refresh_trade_available()
        gateway.broadcast(self.cached_account_payload() or {})

    def kick_refresh(self) -> None:
        self._refresh_wanted = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._refresh_task and not self._refresh_task.done():
            return
        self._refresh_task = loop.create_task(self._refresh_loop())

    async def _refresh_loop(self) -> None:
        await asyncio.sleep(_REFRESH_DELAY)
        while self._refresh_wanted:
            self._refresh_wanted = False
            try:
                self._summary = await self.fetch_account_summary()
                self._orders_by_market = self._index_orders(self._summary.open_orders)
                self._orders_hydrated = True
                self._publish()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("account refresh failed")
            if self._refresh_wanted:
                await asyncio.sleep(_REFRESH_DELAY)

    async def _ws_auth_token(self) -> str | None:
        if not self._auth_token_fn:
            return None
        try:
            return await self._auth_token_fn()
        except Exception:
            logger.warning("account ws auth token error")
            return None

    async def _run_account_ws(self) -> None:
        while True:
            try:
                feed_health.set_account_ws("reconnecting")
                await self._stream_account()
            except asyncio.CancelledError:
                feed_health.set_account_ws("down")
                break
            except Exception:
                logger.exception("account ws error, reconnecting in 3s")
                feed_health.set_account_ws("reconnecting")
                await asyncio.sleep(3)

    async def _account_subscribe(self, ws: Any, account_id: int, auth: str | None) -> None:
        async def sub(channel: str, *, require_auth: bool = False) -> None:
            if require_auth and not auth:
                return
            payload: dict[str, Any] = {"type": "subscribe", "channel": channel}
            if auth:
                payload["auth"] = auth
            await ws.send(json.dumps(payload))

        await sub(f"user_stats/{account_id}")
        await sub(f"account_all_orders/{account_id}", require_auth=True)
        await sub(f"account_all_trades/{account_id}")
        await sub(f"account_all_positions/{account_id}", require_auth=True)
        await sub(f"account_all_assets/{account_id}", require_auth=True)

    @staticmethod
    async def _ws_ping(ws: Any, deadline: float) -> None:
        while time.time() < deadline:
            remaining = deadline - time.time()
            await asyncio.sleep(min(_PING_EVERY, max(0.1, remaining)))
            if time.time() >= deadline:
                return
            await ws.send(json.dumps({"type": "ping"}))

    async def _stream_account(self) -> None:
        account_id = settings.lighter_account_index
        if not account_id:
            feed_health.set_account_ws("down")
            return
        auth = await self._ws_auth_token()
        deadline = time.time() + _ACCOUNT_WS_TTL
        last_msg = time.monotonic()
        async with websockets.connect(settings.ws_url) as ws:
            await self._account_subscribe(ws, account_id, auth)
            feed_health.set_account_ws("live", last_msg_at=int(time.time() * 1000))

            async def recv() -> None:
                nonlocal last_msg
                while time.time() < deadline:
                    timeout = max(1.0, min(5.0, deadline - time.time()))
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except TimeoutError:
                        if time.monotonic() - last_msg >= _SILENCE_S:
                            logger.warning("account ws silent for %.0fs — reconnecting", _SILENCE_S)
                            feed_health.set_account_ws("stale")
                            with contextlib.suppress(Exception):
                                await ws.close()
                            return
                        continue
                    last_msg = time.monotonic()
                    feed_health.touch_account_msg()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                        continue
                    self.handle_account_ws(msg)

            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._ws_ping(ws, deadline))
                tg.create_task(recv())

    @staticmethod
    def _ws_kind(msg: dict[str, Any]) -> tuple[str, str]:
        blob = f"{msg.get('type', '')} {msg.get('channel', '')}"
        action = "subscribed" if "subscribed" in blob else "update"
        for kind in (
            "account_all_orders",
            "account_all_positions",
            "account_all_trades",
            "account_all_assets",
            "user_stats",
        ):
            if kind in blob:
                return action, kind
        raw = str(msg.get("type", ""))
        a, _, rest = raw.partition("/")
        return a, rest.split(":")[0]

    def _apply_collateral(self, msg: dict[str, Any]) -> None:
        self._remember_assets(msg.get("assets"))
        stats = msg.get("stats") if isinstance(msg.get("stats"), dict) else None
        if stats is None and "stats" not in msg:
            stats_obj = msg
        else:
            stats_obj = stats or {}
        collat = msg.get("collateral")
        avail = msg.get("available_balance") or msg.get("available")
        if isinstance(stats_obj, dict):
            if stats_obj.get("collateral") is not None:
                collat = stats_obj["collateral"]
            if stats_obj.get("available_balance") is not None:
                avail = stats_obj["available_balance"]
            elif stats_obj.get("available") is not None:
                avail = stats_obj["available"]
        if collat is not None:
            self._summary.collateral = str(collat)
        if avail is not None:
            self._summary.available = str(avail)
        self._refresh_trade_available(stats_obj if isinstance(stats_obj, dict) else None)

    def _broadcast_trades(self, raw: Any) -> None:
        account_index = settings.lighter_account_index
        if not account_index:
            return
        trades = [
            t
            for t in (desk_account_trade(row, account_index) for row in iter_trade_rows(raw))
            if t is not None
        ]
        if trades:
            gateway.broadcast({"type": "account_trades", "trades": trades})

    def _apply_positions(self, raw: Any, *, snapshot: bool) -> None:
        self._summary.positions = merge_positions(self._summary.positions, raw, snapshot=snapshot)

    def touch_marks(self) -> None:
        """Re-mark open positions from latest market stats and push to the desk."""
        if not self._summary.positions:
            return
        self._publish()

    def handle_account_ws(self, msg: dict[str, Any]) -> None:
        action, kind = self._ws_kind(msg)
        snapshot = action == "subscribed"
        if kind == "account_all_positions":
            if "positions" in msg:
                self._apply_positions(msg.get("positions"), snapshot=snapshot)
            self._publish()
        elif kind == "account_all_assets":
            if "assets" in msg:
                self._remember_assets(msg.get("assets"))
            self._publish()
        elif kind == "account_all_trades":
            self._broadcast_trades(msg.get("trades"))
        elif kind == "account_all_orders":
            if "orders" in msg:
                self._orders_by_market = apply_orders(
                    self._orders_by_market,
                    msg.get("orders"),
                    snapshot=snapshot,
                )
                self._orders_hydrated = True
                self._publish()
        elif kind == "user_stats":
            self._apply_collateral(msg)
            self._publish()
        elif kind not in ("", "pong", "connected", "ping"):
            logger.debug("account ws unhandled type=%s kind=%s", msg.get("type"), kind)

    async def fetch_account_summary(self) -> AccountSummary:
        if not settings.lighter_account_index:
            return AccountSummary(collateral="0", available="0", unrealized_pnl="0")

        account_api = lighter.AccountApi(gateway.client)
        resp = await account_api.account(
            by="index",
            value=str(settings.lighter_account_index),
            active_only=True,
        )
        account = resp.accounts[0] if resp.accounts else None
        if not account:
            return AccountSummary(collateral="0", available="0", unrealized_pnl="0")

        positions: list = []
        for p in getattr(account, "positions", []) or []:
            pos = parse_position(p)
            if pos:
                positions.append(pos)

        open_orders: list[OpenOrder] = []
        orders_loaded = False
        if self._auth_token_fn:
            try:
                auth = await self._auth_token_fn()
                order_api = lighter.OrderApi(gateway.client)
                orders_resp = await order_api.account_active_orders(
                    authorization=auth,
                    account_index=settings.lighter_account_index,
                )
                raw_orders = getattr(orders_resp, "orders", None)
                for rows in incoming_orders_by_market(raw_orders).values():
                    for o in rows:
                        parsed = parse_order(o)
                        if parsed:
                            open_orders.append(parsed)
                orders_loaded = True
            except Exception:
                logger.exception("failed to load open orders")

        assets = getattr(account, "assets", None)
        self._remember_assets(assets)
        available = str(getattr(account, "available_balance", "0"))
        trade_available = self._resolve_trade_available(None, available)
        summary = AccountSummary(
            collateral=str(getattr(account, "collateral", "0")),
            available=available,
            trade_available=trade_available,
            unrealized_pnl=str(getattr(account, "total_unrealized_pnl", "0")),
            positions=positions,
            open_orders=open_orders,
        )
        if orders_loaded:
            self._orders_hydrated = True
        return summary

    async def fetch_account_trades(
        self,
        *,
        market_id: int | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        account_index = settings.lighter_account_index
        if not account_index or not self._auth_token_fn:
            raise ValueError("Account not configured")
        auth = await self._auth_token_fn()
        order_api = lighter.OrderApi(gateway.client)
        resp = await order_api.trades(
            sort_by="timestamp",
            sort_dir="desc",
            limit=min(max(limit, 1), 100),
            authorization=auth,
            account_index=account_index,
            market_id=market_id,
            cursor=cursor,
        )
        trades = [
            row
            for row in (desk_account_trade(t, account_index) for t in (resp.trades or []))
            if row is not None
        ]
        return {"trades": trades, "next_cursor": resp.next_cursor}

    async def fetch_account_funding(
        self,
        *,
        market_id: int | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        account_index = settings.lighter_account_index
        if not account_index or not self._auth_token_fn:
            raise ValueError("Account not configured")
        auth = await self._auth_token_fn()
        account_api = lighter.AccountApi(gateway.client)
        resp = await account_api.position_funding(
            account_index=account_index,
            limit=min(max(limit, 1), 100),
            authorization=auth,
            market_id=market_id,
            cursor=cursor,
        )
        fundings = [desk_position_funding(row) for row in (resp.position_fundings or [])]
        return {"fundings": fundings, "next_cursor": resp.next_cursor}


account_service = AccountService()
