"""The Massager's book. Desk wiring (exclusivity, the desk registry) is phase 3."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

from mayedge import db as store
from mayedge.algos.chase.execution import ChaseExecution
from mayedge.algos.clip_book import AlgoPayload, ClipBook
from mayedge.algos.massager.config import MASSAGER_COI_BASE, MASSAGER_COI_END
from mayedge.algos.massager.job import AtrFn, CloseFn, LastRun, MassagerRunner, venue_position
from mayedge.algos.massager.plan import ALGO_ID, MassagerParams, carry, tally_from_run
from mayedge.algos.massager.state import MassagerRuntime, MassagerState
from mayedge.numbers import fmt_decimal, parse_decimal, to_decimal
from mayedge.rows import obj

ZERO = Decimal("0")

# MS24: the Chop labels the ticket sends.
CHOP_LABELS = ("ranging", "mixed", "trending")

MarketConflictFn = Callable[[int], bool]


class MassagerBook(ClipBook[MassagerRunner]):
    """One Massager per Market (massager-scope.md §3)."""

    ALGO_ID = ALGO_ID
    ID_PREFIX = "MS-"
    LABEL = "Massager"
    COI_BASE = MASSAGER_COI_BASE
    COI_END = MASSAGER_COI_END

    def __init__(
        self,
        *,
        execution: Callable[[], ChaseExecution],
        broadcast: Callable[[AlgoPayload], None],
        coi_base: int | None = None,
        coi_end: int | None = None,
        missing_fill_grace_ms: int = 800,
        market_conflict: MarketConflictFn | None = None,
        atr: AtrFn | None = None,
        close: CloseFn | None = None,
    ) -> None:
        super().__init__(
            execution=execution,
            broadcast=broadcast,
            coi_base=coi_base,
            coi_end=coi_end,
            missing_fill_grace_ms=missing_fill_grace_ms,
        )
        self._market_conflict = market_conflict
        self._atr = atr
        self._close = close

    def set_market_conflict(self, fn: MarketConflictFn) -> None:
        self._market_conflict = fn

    def _new_runner(self) -> MassagerRunner:
        return MassagerRunner(self, self._atr, self._close)

    def _view(self, job: MassagerRunner) -> MassagerState:
        return job.state

    def set_atr(self, fn: AtrFn) -> None:
        self._atr = fn

    def set_close(self, fn: CloseFn) -> None:
        self._close = fn

    def last_run(self, market_index: int) -> LastRun | None:
        """MS22: what the last Massager run on the Market left, from the store."""
        row = store.load_last_run(ALGO_ID, market_index)
        if row is None:
            return None
        rt = MassagerRuntime.from_json(obj(obj(row.get("params_json")).get("runtime")))
        tally = rt.tally
        if tally is None:
            if rt.core == 0:
                return None
            tally = tally_from_run(
                core_size=rt.core,
                core_entry=rt.core_entry,
                book=rt.book,
                since=int(row.get("created_at") or 0),
            )
        return LastRun(
            tally=tally,
            captured=rt.book.captured,
            closed=row.get("reason") == "position_closed",
            algo_id=str(row.get("algo_id") or ""),
        )

    def carry_preview(self, market_index: int) -> dict[str, Any]:
        """MS19, MS22: the Tally a Start would carry now, for the ticket."""
        ex = self.execution()
        position, entry = venue_position(ex.cached_account_payload() or {}, market_index)
        bid_s, ask_s = ex.best_bid_ask(market_index)
        mid = (to_decimal(bid_s) + to_decimal(ask_s)) / 2 if bid_s and ask_s else entry
        last = self.last_run(market_index)
        if position == 0 or mid is None:
            return {"carried": False, "why": "No Position", "source": None}
        took = carry(
            last.tally if last else None,
            last_captured=last.captured if last else ZERO,
            last_closed=last.closed if last else False,
            source=last.algo_id if last else None,
            position=position,
            entry=entry,
            mid=mid,
            since=0,
        )
        b = took.tally.basis()
        return {
            "carried": took.carried,
            "why": took.why,
            "source": took.source,
            "basis": fmt_decimal(b) if b is not None else None,
            "entry": fmt_decimal(took.tally.entry),
            "captured": fmt_decimal(took.tally.captured_before) or "0",
            "runs": took.tally.runs,
        }

    async def start_from_body(self, body: dict[str, Any]) -> None:
        """MS3: a Fixed Step comes as ``step``; an ATR one as ``atr_mult`` and ``atr_tf``."""
        atr = body.get("step_mode") == "atr"
        params = MassagerParams(
            band_low=parse_decimal(str(body["band_low"])),
            band_high=parse_decimal(str(body["band_high"])),
            swing=parse_decimal(str(body["swing"])),
            step=ZERO if atr else parse_decimal(str(body["step"])),
            step_mode="atr" if atr else "fixed",
            atr_mult=parse_decimal(str(body["atr_mult"])) if atr else ZERO,
            atr_tf=str(body.get("atr_tf") or "1h"),
        )
        await self.start(
            market_index=int(body["market_index"]),
            params=params,
            fresh=bool(body.get("fresh")),
            chop=_chop(body.get("chop")),
        )

    async def start(
        self,
        *,
        market_index: int,
        params: MassagerParams,
        fresh: bool = False,
        chop: dict[str, Any] | None = None,
    ) -> None:
        await self._ensure_book(market_index)
        if self.live_on_market(market_index):
            raise ValueError("A Massager is already running on this Market")
        if self._market_conflict and self._market_conflict(market_index):
            raise ValueError("A Planner, Trail or Grid runs this Market's orders")

        last = self.last_run(market_index)

        async def begin(job: MassagerRunner, algo_id: str) -> None:
            await job.start(
                algo_id=algo_id,
                market_index=market_index,
                params=params,
                last=last,
                fresh=fresh,
                chop=chop,
            )

        await self._launch(begin)


def _chop(raw: Any) -> dict[str, Any] | None:
    """MS24: the ticket's Chop reading, kept with the run. Anything malformed is dropped."""
    if not isinstance(raw, dict):
        return None
    reading = cast(dict[str, Any], raw)
    label = str(reading.get("label") or "")
    if label not in CHOP_LABELS:
        return None
    try:
        out: dict[str, Any] = {"label": label, "er": fmt_decimal(parse_decimal(str(reading["er"])))}
        for key in ("band_low", "band_high"):
            if reading.get(key) not in (None, ""):
                out[key] = fmt_decimal(parse_decimal(str(reading[key])))
    except (KeyError, ValueError, ArithmeticError):
        return None
    out["tf"] = "1h"
    out["n"] = int(reading.get("n") or 24)
    return out
