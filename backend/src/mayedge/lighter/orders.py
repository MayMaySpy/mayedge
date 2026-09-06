from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

import lighter

from mayedge.config import settings
from mayedge.lighter.account import account_service
from mayedge.lighter.coi import init_manual_coi_seq, next_manual_client_order_index
from mayedge.lighter.gateway import gateway
from mayedge.lighter.models import (
    from_scaled,
    leverage_to_imf,
    maker_min_base,
    parse_to_int,
)
from mayedge.numbers import check_notional, fmt_decimal

logger = logging.getLogger(__name__)


class OrderService:
    """SignerClient order placement; account state lives in account_service."""

    def __init__(self) -> None:
        self._signer: lighter.SignerClient | None = None

    async def start(self) -> None:
        key = settings.lighter_api_private_key
        account_index = settings.lighter_account_index
        if key and account_index is not None:
            self._signer = lighter.SignerClient(
                url=settings.base_url,
                api_private_keys={settings.lighter_api_key_index: key},
                account_index=account_index,
            )
            account_service.set_auth_token_fn(self._auth_token)
            init_manual_coi_seq()
        else:
            logger.warning("Trading disabled: missing API credentials")
            account_service.set_auth_token_fn(None)
        await account_service.start()

    async def stop(self) -> None:
        await account_service.stop()
        if self._signer:
            await self._signer.close()
            self._signer = None

    @property
    def enabled(self) -> bool:
        return self._signer is not None

    @property
    def signer(self) -> lighter.SignerClient:
        if not self._signer:
            raise RuntimeError("Trading not configured")
        return self._signer

    def _market_meta(self, market_index: int):
        meta = gateway.get_market_by_index(market_index)
        if not meta:
            raise ValueError(f"Unknown market index {market_index}")
        return meta

    def _scale_size(self, size: str, decimals: int) -> int:
        amount = parse_to_int(size, decimals)
        if amount <= 0:
            raise ValueError("Size too small")
        return amount

    def _scale_price(self, price: str, decimals: int) -> int:
        amount = parse_to_int(price, decimals)
        if amount <= 0:
            raise ValueError("Enter a price")
        return amount

    def _check_maker_size(self, meta, size_int: int, price_int: int | None) -> None:
        qty = from_scaled(size_int, meta.size_decimals)
        px = from_scaled(price_int, meta.price_decimals) if price_int else None
        need = maker_min_base(meta.min_base_amount, meta.min_quote_amount, px)
        if qty >= need:
            return
        need_s = fmt_decimal(need) or "0"
        quote_s = fmt_decimal(Decimal(str(meta.min_quote_amount or 0))) or "0"
        raise ValueError(f"Min {need_s} {meta.symbol} (or ${quote_s})")

    @staticmethod
    def _is_maker_tif(time_in_force: str) -> bool:
        return time_in_force.lower() in {"gtt", "post_only", "gtc"}

    @staticmethod
    def _is_ask(side: str) -> bool:
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        return side == "sell"

    def _check_notional(self, meta, size_int: int, price_int: int | None = None) -> None:
        qty = from_scaled(size_int, meta.size_decimals)
        if price_int is not None:
            px = from_scaled(price_int, meta.price_decimals)
        else:
            px = Decimal(str(meta.last_trade_price or meta.mark_price or 0))
        check_notional(qty, px, settings.max_order_notional)

    def _raise_order_err(self, err: Any, meta) -> None:
        text = str(err)
        if "21706" in text or "invalid order base or quote amount" in text.lower():
            raise ValueError(
                f"Min {meta.min_base_amount} {meta.symbol} or ${meta.min_quote_amount}"
            )
        raise ValueError(err)

    @staticmethod
    def _is_invalid_nonce(err: Any) -> bool:
        text = str(err or "").lower()
        return "21104" in text or "invalid nonce" in text

    def _nonce_stale(self, ret: Any, err: Any) -> bool:
        if self._is_invalid_nonce(err):
            return True
        if ret is None:
            return False
        return self._is_invalid_nonce(getattr(ret, "code", None)) or self._is_invalid_nonce(
            getattr(ret, "message", None)
        )

    async def _refresh_nonce(self) -> None:
        nm = getattr(self.signer, "nonce_manager", None)
        refresh = getattr(nm, "async_hard_refresh_nonce", None)
        if refresh is None:
            return
        keys = list(getattr(nm, "api_keys_list", None) or [settings.lighter_api_key_index])
        for key in keys:
            try:
                await refresh(int(key))
            except Exception:
                logger.warning("nonce refresh failed for key %s", key, exc_info=True)

    async def _retry_nonce(self, send):
        created, ret, err = await send()
        if not self._nonce_stale(ret, err):
            return created, ret, err
        logger.warning("invalid nonce, refreshing and retrying once")
        await self._refresh_nonce()
        return await send()

    @staticmethod
    def _require_tx(resp: Any, err: Any, *, action: str) -> str:
        if err:
            raise ValueError(err)
        if resp is None:
            raise ValueError(f"{action} failed")
        code = getattr(resp, "code", None)
        if code is not None and int(code) != 200:
            msg = getattr(resp, "message", None) or f"{action} failed ({code})"
            raise ValueError(msg)
        tx_hash = getattr(resp, "tx_hash", None)
        return str(tx_hash) if tx_hash else str(resp)

    def cached_account_payload(self) -> dict[str, Any] | None:
        return account_service.cached_account_payload()

    def kick_refresh(self) -> None:
        account_service.kick_refresh()

    async def get_account_summary(self):
        return await account_service.fetch_account_summary()

    async def get_account_trades(self, **kwargs: Any) -> dict[str, Any]:
        return await account_service.fetch_account_trades(**kwargs)

    async def get_account_funding(self, **kwargs: Any) -> dict[str, Any]:
        return await account_service.fetch_account_funding(**kwargs)

    async def _auth_token(self) -> str:
        if not self.enabled:
            raise ValueError("Trading not configured")
        auth, err = self.signer.create_auth_token_with_expiry()
        if err:
            raise ValueError(err)
        if not auth:
            raise ValueError("empty auth token")
        return auth

    def _next_client_order_index(self) -> int:
        return next_manual_client_order_index()

    async def create_market_order(
        self,
        market_index: int,
        side: str,
        size: str,
        slippage: float = 0.01,
        reduce_only: bool = False,
        client_order_index: int | None = None,
    ) -> dict[str, Any]:
        meta = self._market_meta(market_index)
        base_amount = self._scale_size(size, meta.size_decimals)
        self._check_notional(meta, base_amount)
        is_ask = self._is_ask(side)
        coi = client_order_index or self._next_client_order_index()

        _tx, tx_hash, err = await self.signer.create_market_order_if_slippage(
            market_index=market_index,
            client_order_index=coi,
            base_amount=base_amount,
            max_slippage=slippage,
            is_ask=is_ask,
            reduce_only=reduce_only,
        )
        if err:
            self._raise_order_err(err, meta)
        return {"tx_hash": tx_hash, "client_order_index": coi}

    async def create_limit_order(
        self,
        market_index: int,
        side: str,
        size: str,
        price: str,
        time_in_force: str = "gtt",
        reduce_only: bool = False,
        client_order_index: int | None = None,
    ) -> dict[str, Any]:
        meta = self._market_meta(market_index)
        base_amount = self._scale_size(size, meta.size_decimals)
        price_int = self._scale_price(price, meta.price_decimals)
        if self._is_maker_tif(time_in_force):
            self._check_maker_size(meta, base_amount, price_int)
        self._check_notional(meta, base_amount, price_int)
        is_ask = self._is_ask(side)
        coi = client_order_index or self._next_client_order_index()

        tif_map = {
            "ioc": self.signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
            "gtt": self.signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
            "post_only": self.signer.ORDER_TIME_IN_FORCE_POST_ONLY,
        }
        tif = tif_map.get(time_in_force.lower(), self.signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME)

        _tx, tx_hash, err = await self._retry_nonce(
            lambda: self.signer.create_order(
                market_index=market_index,
                client_order_index=coi,
                base_amount=base_amount,
                price=price_int,
                is_ask=is_ask,
                order_type=self.signer.ORDER_TYPE_LIMIT,
                time_in_force=tif,
                reduce_only=reduce_only,
                order_expiry=self.signer.DEFAULT_28_DAY_ORDER_EXPIRY,
            )
        )
        if err:
            self._raise_order_err(err, meta)
        return {"tx_hash": tx_hash, "client_order_index": coi}

    async def create_twap_order(
        self,
        market_index: int,
        side: str,
        size: str,
        duration_seconds: int,
        max_slippage: float = 0.01,
        reduce_only: bool = False,
        client_order_index: int | None = None,
    ) -> dict[str, Any]:
        meta = self._market_meta(market_index)
        base_amount = self._scale_size(size, meta.size_decimals)
        ref_px = meta.last_trade_price or meta.mark_price or 0
        bid_s, ask_s = gateway.best_bid_ask(market_index)
        mid = 0.0
        if bid_s and ask_s:
            bid = float(bid_s)
            ask = float(ask_s)
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
        spot = mid or ref_px
        if spot <= 0:
            raise ValueError("Cannot price TWAP order — no reference price")
        slip = max(0.0, min(float(max_slippage), 0.05))
        worst = spot * (1 + slip) if side == "buy" else spot * (1 - slip)
        if worst <= 0:
            raise ValueError("Invalid TWAP worst price")
        self._check_notional(meta, base_amount, self._scale_price(str(worst), meta.price_decimals))
        is_ask = self._is_ask(side)
        coi = client_order_index or self._next_client_order_index()
        expiry_ms = int(time.time() * 1000) + duration_seconds * 1000
        price_int = self._scale_price(str(worst), meta.price_decimals)

        _tx, tx_hash, err = await self.signer.create_order(
            market_index=market_index,
            client_order_index=coi,
            base_amount=base_amount,
            price=price_int,
            is_ask=is_ask,
            order_type=self.signer.ORDER_TYPE_TWAP,
            time_in_force=self.signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
            reduce_only=reduce_only,
            order_expiry=expiry_ms,
        )
        if err:
            self._raise_order_err(err, meta)
        return {"tx_hash": tx_hash, "client_order_index": coi}

    async def modify_order(
        self,
        market_index: int,
        order_index: int,
        price: str,
        *,
        size: str | None = None,
    ) -> dict[str, Any]:
        """Amend a live order. order_index may be exchange index or client_order_index."""
        meta = self._market_meta(market_index)
        price_int = self._scale_price(price, meta.price_decimals)
        if size is not None:
            base_amount = self._scale_size(size, meta.size_decimals)
            self._check_maker_size(meta, base_amount, price_int)
            self._check_notional(meta, base_amount, price_int)
        else:
            base_amount = 0  # NilOrderBaseAmount — leave size unchanged
        _tx, resp, err = await self._retry_nonce(
            lambda: self.signer.modify_order(
                market_index=market_index,
                order_index=order_index,
                base_amount=base_amount,
                price=price_int,
            )
        )
        if err:
            self._raise_order_err(err, meta)
        tx_hash = self._require_tx(resp, err, action="Modify")
        return {"tx_hash": tx_hash}

    async def cancel_order(self, market_index: int, order_index: int) -> dict[str, Any]:
        _tx, resp, err = await self._retry_nonce(
            lambda: self.signer.cancel_order(
                market_index=market_index,
                order_index=order_index,
            )
        )
        tx_hash = self._require_tx(resp, err, action="Cancel")
        return {"tx_hash": tx_hash}

    async def cancel_all_orders(self, market_index: int | None = None) -> dict[str, Any]:
        idx = self.signer.NIL_MARKET_INDEX if market_index is None else market_index
        _tx, resp, err = await self.signer.cancel_all_orders(
            time_in_force=self.signer.CANCEL_ALL_TIF_IMMEDIATE,
            timestamp_ms=int(time.time() * 1000),
            cancel_all_market_index=idx,
        )
        tx_hash = self._require_tx(resp, err, action="Cancel all")
        return {"tx_hash": tx_hash}

    async def update_leverage(
        self, market_index: int, leverage: int, cross: bool = True
    ) -> dict[str, Any]:
        meta = self._market_meta(market_index)
        allowed = meta.allowed_leverages
        if leverage not in allowed:
            opts = ", ".join(f"{x}x" for x in allowed) or f"1–{meta.max_leverage}x"
            raise ValueError(f"{meta.symbol} leverage must be one of {opts}")
        imf = leverage_to_imf(leverage, meta.min_initial_margin_fraction)
        margin_mode = 0 if cross else 1
        _tx, tx_hash, err = await self.signer.update_leverage(
            market_index=market_index,
            margin_mode=margin_mode,
            leverage=leverage,
        )
        if err:
            raise ValueError(err)
        return {
            "tx_hash": tx_hash,
            "leverage": leverage,
            "imf": imf,
            "max_leverage": meta.max_leverage,
        }


order_service = OrderService()
