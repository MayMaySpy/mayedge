"""Telegram pushes: pace, retry, debounce, and one text per event."""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
import tempfile
import time
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from httpx import ASGITransport, AsyncClient

from mayedge import db as store
from mayedge.api.app import create_app
from mayedge.config import settings
from mayedge.journal import RoundTrip
from mayedge.persist_portfolio import portfolio_put_buckets
from mayedge.push import (
    HttpxTransport,
    PushRouter,
    PushSettings,
    SendResult,
    TelegramPusher,
    boot_text,
    daily_journal_text,
    daily_text,
    journal_day_totals,
    portfolio_day_totals,
    public_push_status,
    push_settings_from_dict,
)


class ManualClock:
    def __init__(self, t: float = 1_700_000_000.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t

    def mono(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.t += seconds
        await asyncio.sleep(0)


class RecordingTransport:
    def __init__(self, clock: ManualClock | None = None) -> None:
        self.clock = clock
        self.sent: list[tuple[float, str]] = []
        self.results: list[SendResult] = []

    async def send_message(self, text: str) -> SendResult:
        when = self.clock.mono() if self.clock is not None else 0.0
        self.sent.append((when, text))
        if self.results:
            return self.results.pop(0)
        return SendResult(200)


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool]] = []

    def push(self, key: str, text: str, *, urgent: bool = False, force: bool = False) -> None:
        self.rows.append((key, text, urgent))


def _fill(seq: int, qty: str, price: str) -> dict[str, object]:
    return {"clip_seq": seq, "qty": qty, "price": price}


def _planner(
    *,
    status: str = "running",
    fills: list[dict[str, object]] | None = None,
    entry_filled: str = "0",
    error: str | None = None,
) -> dict[str, object]:
    return {
        "algo_id": "p1",
        "algo_type": "planner",
        "status": status,
        "symbol": "ETH",
        "side": "buy",
        "error": error,
        "planner": {
            "roles": {"1": "entry", "2": "stop", "3": "tp1"},
            "entry_filled": entry_filled,
            "plan": {
                "stop": "2390",
                "risk_usd": "60",
                "targets": [{"index": 1, "r": "2"}],
            },
        },
        "fills": fills or [],
    }


def _trail(
    *,
    filled: str = "0",
    kind: str = "entry",
    status: str = "running",
    fills: list[dict[str, object]] | None = None,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "algo_id": "t1",
        "algo_type": "trail",
        "status": status,
        "symbol": "ETH",
        "side": "sell",
        "filled": filled,
        "rest_price": "2400",
        "error": error,
        "trail": {"kind": kind},
        "fills": fills or [],
    }


def _algo(*rows: dict[str, object]) -> dict[str, object]:
    return {"type": "algo", "working": list(rows), "history": []}


def _utc_stamp(hour: int, minute: int, *, second: int = 30, day_offset: int = 0) -> float:
    base = time.gmtime(1_700_000_000)
    return float(
        calendar.timegm((base.tm_year, base.tm_mon, base.tm_mday + day_offset, hour, minute, second, 0, 0, 0))
    )


def _trip(**overrides: object) -> RoundTrip:
    fields: dict[str, object] = {
        "trip_key": "1:1",
        "market_index": 1,
        "symbol": "ETH",
        "side": "long",
        "open_ts": 1,
        "close_ts": 1_700_000_000,
        "size": Decimal("1"),
        "avg_in": Decimal("1"),
        "avg_out": Decimal("1"),
        "pnl": Decimal("0"),
        "fees": Decimal("0"),
        "funding": Decimal("0"),
        "net": Decimal("0"),
        "algo": "manual",
        "algo_id": None,
        "r": None,
        "partial": False,
        "partial_reason": None,
        "open": False,
        "upnl": None,
        "fills": (),
    }
    fields.update(overrides)
    return RoundTrip(**fields)  # type: ignore[arg-type]


class RouterTests(unittest.TestCase):
    def _router(self, cfg: PushSettings | None = None) -> tuple[PushRouter, Sink, ManualClock]:
        sink = Sink()
        clock = ManualClock()
        return PushRouter(sink, cfg or PushSettings(), clock), sink, clock

    def test_boot_text_counts(self) -> None:
        self.assertEqual(
            boot_text("mainnet", 3, 2),
            "Desk up (mainnet) — 3 algos restored, 2 Positions open",
        )
        self.assertEqual(
            boot_text("testnet", 1, 1),
            "Desk up (testnet) — 1 algo restored, 1 Position open",
        )

    def test_a_long_gap_names_the_down_and_is_the_urgent_line(self) -> None:
        start = int(datetime(2026, 10, 21, 2, 10, tzinfo=UTC).timestamp() * 1000)
        end = int(datetime(2026, 10, 21, 4, 24, tzinfo=UTC).timestamp() * 1000)
        text = boot_text("mainnet", 3, 2, {"from": start, "to": end, "clean": False})
        self.assertEqual(
            text,
            "Desk up (mainnet) after 2h 14m down (02:10–04:24 UTC, not a clean stop). "
            "Trails, Planner trailing parts and Auto kill were not watching; venue stops held. "
            "3 algos restored, 2 Positions open.",
        )
        clean = boot_text("mainnet", 3, 2, {"from": start, "to": end, "clean": True})
        self.assertIn("clean stop", clean)
        self.assertNotIn("not a clean stop", clean)

    def test_desk_freeze_pushes_once_and_urgent(self) -> None:
        router, sink, _clock = self._router()
        start = int(datetime(2026, 10, 21, 2, 10, tzinfo=UTC).timestamp() * 1000)
        end = start + 14 * 60 * 1000
        router.on_message({"type": "desk_freeze", "from": start, "to": end})
        self.assertEqual(len(sink.rows), 1)
        key, text, urgent = sink.rows[0]
        self.assertEqual(key, f"freeze:{end}")
        self.assertTrue(urgent)
        self.assertIn("Desk was frozen 14m (02:10–02:24 UTC)", text)
        self.assertIn("Positions unknown until the account feed is back", text)
        router.on_message(
            {
                "type": "feed_health",
                "account_ws": "live",
                "market_ws": "live",
                "venue_down_since": 0,
            }
        )
        router.on_message(
            {
                "type": "account",
                "unrealized_pnl": "-120",
                "positions": [
                    {"symbol": "ETH", "size": "1"},
                    {"symbol": "BTC", "size": "-2"},
                ],
            }
        )
        later = end + 14 * 60 * 1000
        router.on_message({"type": "desk_freeze", "from": end, "to": later})
        key, text, urgent = sink.rows[-1]
        self.assertEqual(key, f"freeze:{later}")
        self.assertTrue(urgent)
        self.assertIn("2 Positions open, uPnL −$120", text)

    def test_bad_push_block_falls_back(self) -> None:
        cfg = push_settings_from_dict(
            {"push": {"alerts": "nope", "algos": "nope", "max_per_min": 0}}
        )
        self.assertEqual(cfg.alerts, "held")
        self.assertEqual(cfg.algos, "lifecycle")
        self.assertEqual(cfg.max_per_min, 1)
        self.assertEqual(cfg.daily_at, "")

    def test_daily_at_parses_hhmm_or_stays_off(self) -> None:
        self.assertEqual(PushSettings().daily_at, "")
        self.assertEqual(push_settings_from_dict({"push": {"daily_at": "8:00"}}).daily_at, "08:00")
        self.assertEqual(push_settings_from_dict({"push": {"daily_at": "25:99"}}).daily_at, "")
        self.assertEqual(push_settings_from_dict({"push": {}}).daily_at, "")

    def test_daily_journal_text(self) -> None:
        self.assertEqual(
            daily_journal_text(9, 412, 38, -6),
            "Yesterday: Net +$412 over 9 Round trips, fees $38, funding −$6",
        )
        self.assertEqual(
            daily_journal_text(1, -12, -3, 1),
            "Yesterday: Net −$12 over 1 Round trip, fees $3, funding +$1",
        )
        self.assertEqual(daily_journal_text(0, 0, 0, 0), "Yesterday: no Round trips.")
        self.assertEqual(
            daily_journal_text(1, 6.54, 0, 0.049),
            "Yesterday: Net +$7 over 1 Round trip, fees $0, funding $0",
            "an amount that rounds to $0 carries no sign",
        )

    def test_journal_day_totals_keeps_that_utc_day(self) -> None:
        trips = [
            _trip(trip_key="a", net=Decimal("400"), fees=Decimal("30"), funding=Decimal("-4")),
            _trip(trip_key="b", net=Decimal("12"), fees=Decimal("8"), funding=Decimal("-2")),
            _trip(trip_key="partial", partial=True, net=Decimal("999")),
            _trip(trip_key="open", open=True, close_ts=None, net=Decimal("999")),
            _trip(trip_key="other", close_ts=1_700_000_000 - 86_400, net=Decimal("999")),
        ]
        with patch("mayedge.api.routes.journal._trips", return_value=trips):
            self.assertEqual(journal_day_totals("2023-11-14"), (2, 412.0, 38.0, -6.0))
            self.assertEqual(journal_day_totals("2023-11-13"), (1, 999.0, 0.0, 0.0))
            self.assertEqual(journal_day_totals("2023-11-12"), (0, 0.0, 0.0, 0.0))

    def test_daily_push_stays_off_until_the_knob_is_set(self) -> None:
        called = False

        def journal(day: str) -> tuple[int, float, float, float]:
            nonlocal called
            called = True
            return (1, 1.0, 0.0, 0.0)

        sink = Sink()
        clock = ManualClock(_utc_stamp(8, 0))
        router = PushRouter(sink, PushSettings(), clock, journal=journal)
        router.poll()
        self.assertFalse(called)
        self.assertEqual(sink.rows, [])

    def test_daily_journal_push_is_once_per_local_day(self) -> None:
        days: list[str] = []

        def journal(day: str) -> tuple[int, float, float, float]:
            days.append(day)
            return (9, 412.0, 38.0, -6.0)

        sink = Sink()
        clock = ManualClock(_utc_stamp(7, 59))
        router = PushRouter(sink, PushSettings(daily_at="08:00"), clock, journal=journal)
        router.poll()
        self.assertEqual(sink.rows, [])
        wait = router.due_in()
        self.assertIsNotNone(wait)
        assert wait is not None
        self.assertGreater(wait, 0)
        self.assertLess(wait, 120)

        clock.t = _utc_stamp(8, 0)
        router.poll()
        today = time.strftime("%Y-%m-%d", time.gmtime(clock.t))
        yesterday = time.strftime("%Y-%m-%d", time.gmtime(clock.t - 86_400))
        self.assertEqual(days, [yesterday])
        self.assertEqual(
            sink.rows,
            [
                (
                    f"journal:{today}",
                    "Yesterday: Net +$412 over 9 Round trips, fees $38, funding −$6",
                    False,
                )
            ],
        )
        later = router.due_in()
        self.assertIsNotNone(later)
        assert later is not None
        self.assertGreater(later, 3_600)
        router.poll()
        self.assertEqual(len(sink.rows), 1)

        clock.t = _utc_stamp(8, 0, day_offset=1)
        router.poll()
        self.assertEqual(len(sink.rows), 2)
        self.assertEqual(len(days), 2)

    def test_daily_text_leads_with_the_portfolio(self) -> None:
        # LLP moved less than a dollar: in the total, not named.
        portfolio = {"perps": 380.0, "spot": 40.0, "llp": 0.2, "staking": -8.0}
        self.assertEqual(
            daily_text(9, 380, 38, -6, portfolio),
            "Yesterday: Portfolio +$412 (Perps +$380, Spot +$40, Staking −$8) · "
            "Net +$380 over 9 Round trips, fees $38, funding −$6",
        )
        self.assertEqual(
            daily_text(0, 0, 0, 0, {"perps": 0.0, "spot": 0.0, "llp": 0.0, "staking": 25.0}),
            "Yesterday: Portfolio +$25 (Staking +$25) · no Round trips.",
        )
        self.assertEqual(daily_text(9, 412, 38, -6, None), daily_journal_text(9, 412, 38, -6))

    def test_the_daily_push_carries_the_portfolio_and_survives_its_failure(self) -> None:
        def journal(day: str) -> tuple[int, float, float, float]:
            return (9, 380.0, 38.0, -6.0)

        def portfolio(day: str) -> dict[str, float] | None:
            return {"perps": 380.0, "spot": 40.0, "llp": 0.0, "staking": -8.0}

        def broken(day: str) -> dict[str, float] | None:
            raise RuntimeError("locked")

        sink = Sink()
        router = PushRouter(
            sink, PushSettings(daily_at="08:00"), ManualClock(_utc_stamp(8, 0)), journal=journal, portfolio=portfolio
        )
        router.poll()
        self.assertTrue(sink.rows[0][1].startswith("Yesterday: Portfolio +$412 (Perps +$380"))
        sink = Sink()
        router = PushRouter(
            sink, PushSettings(daily_at="08:00"), ManualClock(_utc_stamp(8, 0)), journal=journal, portfolio=broken
        )
        with self.assertLogs("mayedge.push_router", level="WARNING"):
            router.poll()
        self.assertEqual(sink.rows[0][1], "Yesterday: Net +$380 over 9 Round trips, fees $38, funding −$6")

    def test_a_failed_journal_read_does_not_stop_the_push(self) -> None:
        def journal(day: str) -> tuple[int, float, float, float]:
            raise RuntimeError("locked")

        sink = Sink()
        clock = ManualClock(_utc_stamp(8, 0))
        router = PushRouter(sink, PushSettings(daily_at="08:00"), clock, journal=journal)
        with self.assertLogs("mayedge.push_router", level="WARNING") as logs:
            router.poll()
        router.poll()
        self.assertEqual(sink.rows, [])
        self.assertIn("daily journal push skipped", logs.output[0])

    def test_status_hides_the_token(self) -> None:
        token = "super-secret-token"
        chat = "4242424242"
        with (
            patch.object(settings, "telegram_bot_token", token),
            patch.object(settings, "telegram_chat_id", chat),
        ):
            body = public_push_status()
        blob = json.dumps(body)
        self.assertNotIn(token, blob)
        self.assertNotIn(chat, blob)
        self.assertEqual(set(body), {"enabled", "chat_set", "alerts", "algos"})
        self.assertTrue(body["enabled"])
        self.assertTrue(body["chat_set"])

    def test_near_liq_and_held_spike(self) -> None:
        router, sink, _clock = self._router()
        router.on_message(
            {
                "type": "alerts",
                "events": [
                    {
                        "id": "n1",
                        "symbol": "ETH",
                        "rule": "near_liq",
                        "severity": 3,
                        "held": "",
                        "note": "near",
                        "price": 2412.5,
                        "facts": [{"kind": "near_liq", "value": 4.6, "liquidation_price": 2301}],
                    },
                    {
                        "id": "h1",
                        "symbol": "ETH",
                        "rule": "price_spike",
                        "severity": 2,
                        "held": "position",
                        "note": "ignored",
                        "facts": [{"kind": "move", "multiple": 3.1, "value": 0.8}],
                    },
                    {
                        "id": "o1",
                        "symbol": "BTC",
                        "rule": "volume_spike",
                        "severity": 2,
                        "held": "",
                        "note": "BTC volume 4×",
                        "facts": [],
                    },
                ],
            }
        )
        self.assertEqual(
            sink.rows,
            [
                (
                    "alert:n1",
                    "🔴 ETH near liquidation — mark 2,412.5, liq 2,301 (4.6%)",
                    True,
                ),
                (
                    "alert:h1",
                    "ETH spike: price 3.1× the hour's biggest minute, +0.8% · held",
                    False,
                ),
            ],
        )

    def test_alert_modes(self) -> None:
        event = {
            "id": "o1",
            "symbol": "BTC",
            "rule": "volume_spike",
            "severity": 2,
            "held": "",
            "note": "BTC volume 4×",
            "facts": [],
        }
        held, sink, _ = self._router(PushSettings(alerts="held"))
        held.on_message({"type": "alerts", "events": [event]})
        self.assertEqual(sink.rows, [])

        urgent, sink, _ = self._router(PushSettings(alerts="urgent"))
        urgent.on_message({"type": "alerts", "events": [event]})
        self.assertEqual(sink.rows, [])
        urgent.on_message({"type": "alerts", "events": [{**event, "severity": 3}]})
        self.assertEqual(sink.rows, [("alert:o1", "BTC volume 4×", False)])

        everything, sink, _ = self._router(PushSettings(alerts="all"))
        everything.on_message({"type": "alerts", "events": [event]})
        self.assertEqual(sink.rows, [("alert:o1", "BTC volume 4×", False)])

        off, sink, _ = self._router(PushSettings(alerts="off"))
        off.on_message(
            {
                "type": "alerts",
                "events": [{**event, "rule": "near_liq", "severity": 3, "price": 1, "facts": []}],
            }
        )
        self.assertEqual(sink.rows, [])

    def test_auto_kill_fire_and_partial(self) -> None:
        router, sink, _clock = self._router()
        seed = {
            "type": "auto_kill",
            "fired_at": None,
            "last_kill_status": None,
            "loss_usd": 800,
            "profit_usd": None,
        }
        router.on_message(seed)
        self.assertEqual(sink.rows, [])
        router.on_message(
            {
                **seed,
                "fired_at": 99,
                "fired_reason": "loss",
                "fired_upnl": -812,
                "last_kill_status": None,
            }
        )
        self.assertEqual(
            sink.rows,
            [
                (
                    "autokill:99",
                    "⛔ Auto kill fired: uPnL −$812 crossed the −$800 floor. "
                    "Stopping algos, cancelling, flattening.",
                    True,
                )
            ],
        )
        router.on_message({"type": "account", "positions": [{"symbol": "ETH", "size": "-2"}]})
        router.on_message({**seed, "fired_at": 99, "last_kill_status": "partial"})
        self.assertEqual(
            sink.rows[-1],
            (
                "autokill:99:result",
                "⚠️ Auto kill could not flatten after 3 tries — 1 Position open: ETH −2.0",
                True,
            ),
        )

    def test_auto_kill_flattened_and_profit(self) -> None:
        router, sink, _clock = self._router()
        router.on_message({"type": "auto_kill", "fired_at": None, "last_kill_status": None})
        router.on_message(
            {
                "type": "auto_kill",
                "fired_at": 7,
                "fired_reason": "profit",
                "fired_upnl": 1100,
                "profit_usd": 1000,
                "loss_usd": 800,
                "last_kill_status": "killed",
            }
        )
        self.assertEqual(
            sink.rows[0][1],
            (
                "⛔ Auto kill fired: uPnL +$1,100 crossed the +$1,000 target. "
                "Stopping algos, cancelling, flattening."
            ),
        )
        self.assertEqual(sink.rows[1][1], "Auto kill: flattened, 0 Positions open")

    def test_first_algo_snapshot_pushes_nothing(self) -> None:
        router, sink, _clock = self._router()
        router.on_message(_algo(_planner(status="error", error="book rejected")))
        self.assertEqual(sink.rows, [])
        router.on_message(_algo(_planner(status="running")))
        self.assertEqual(sink.rows, [])
        router.on_message(_algo(_planner(status="error", error="book rejected")))
        self.assertEqual(
            sink.rows,
            [("algo:p1:error", "Planner ETH stopped with an error: book rejected", False)],
        )

    def test_planner_lifecycle(self) -> None:
        router, sink, _clock = self._router()
        router.on_message(_algo(_planner()))
        router.on_message(
            _algo(
                _planner(
                    fills=[_fill(1, "1.5", "2430")],
                    entry_filled="1.5",
                )
            )
        )
        router.on_message(
            _algo(
                _planner(
                    fills=[_fill(1, "1.5", "2430"), _fill(2, "1.5", "2300")],
                    entry_filled="1.5",
                )
            )
        )
        router.on_message(
            _algo(
                _planner(
                    fills=[
                        _fill(1, "1.5", "2430"),
                        _fill(2, "1.5", "2300"),
                        _fill(3, "0.5", "2510"),
                    ],
                    entry_filled="1.5",
                )
            )
        )
        router.on_message(
            _algo(
                _planner(
                    status="done",
                    fills=[
                        _fill(1, "1.5", "2430"),
                        _fill(2, "1.5", "2300"),
                        _fill(3, "0.5", "2510"),
                    ],
                    entry_filled="1.5",
                )
            )
        )
        self.assertEqual(
            [row[1] for row in sink.rows],
            [
                "Planner ETH long: entry filled 1.5 @ 2,430 · stop 2,390 · risk $60",
                "Planner ETH: stop filled @ 2,300",
                "Planner ETH: target 1 filled @ 2,510 (+2.0R)",
                "Planner ETH long: done",
            ],
        )

    def test_trail_entry_and_chase_error_only(self) -> None:
        router, sink, _clock = self._router()
        chase = {
            "algo_id": "c1",
            "algo_type": "chase",
            "status": "running",
            "symbol": "ETH",
            "side": "buy",
            "error": None,
        }
        router.on_message(_algo(_trail(), chase))
        self.assertEqual(sink.rows, [])
        router.on_message(
            _algo(
                _trail(filled="1.5", fills=[{"price": "2412.5"}]),
                {**chase, "status": "done"},
            )
        )
        self.assertEqual(
            [row[1] for row in sink.rows],
            ["Trail ETH short: entry filled 1.5 @ 2,412.5"],
        )
        router.on_message(
            _algo(_trail(filled="1.5"), {**chase, "status": "error", "error": "rejected"})
        )
        self.assertEqual(sink.rows[-1][1], "Chase ETH stopped with an error: rejected")

    def test_errors_mode_skips_lifecycle(self) -> None:
        router, sink, _clock = self._router(PushSettings(algos="errors"))
        router.on_message(_algo(_planner()))
        router.on_message(_algo(_planner(fills=[_fill(1, "1", "100")], entry_filled="1")))
        self.assertEqual(sink.rows, [])

    def test_venue_down_and_back(self) -> None:
        router, sink, clock = self._router()
        since = clock.t
        router.on_message(
            {
                "type": "feed_health",
                "account_ws": "live",
                "venue_down_since": int(since * 1000),
                "venue_down_reason": "503",
            }
        )
        self.assertEqual(sink.rows, [])
        clock.t += 60
        router.poll()
        when = time.strftime("%H:%M", time.gmtime(since))
        self.assertEqual(sink.rows[-1][1], f"Lighter down since {when} UTC (503)")
        clock.t = since + 360
        router.on_message(
            {
                "type": "feed_health",
                "account_ws": "live",
                "venue_down_since": 0,
                "venue_down_reason": "",
            }
        )
        self.assertEqual(sink.rows[-1], ("venue", "Lighter back after 6m", False))

    def test_account_stale_while_algos_are_live(self) -> None:
        router, sink, clock = self._router()
        router.on_message(
            {"type": "feed_health", "account_ws": "reconnecting", "venue_down_since": 0}
        )
        router.on_message(
            _algo(
                {
                    "algo_id": "a",
                    "algo_type": "chase",
                    "status": "running",
                    "symbol": "ETH",
                },
                {
                    "algo_id": "b",
                    "algo_type": "grid",
                    "status": "paused",
                    "symbol": "BTC",
                },
            )
        )
        self.assertEqual(sink.rows, [])
        clock.t += 120
        router.poll()
        self.assertEqual(
            sink.rows,
            [
                (
                    "account_stale",
                    "⚠️ Account feed stale 2m with 2 algos live — desk is blind",
                    True,
                )
            ],
        )
        router.poll()
        self.assertEqual(len(sink.rows), 1)
        router.on_message({"type": "feed_health", "account_ws": "live", "venue_down_since": 0})
        router.on_message({"type": "feed_health", "account_ws": "stale", "venue_down_since": 0})
        clock.t += 120
        router.poll()
        self.assertEqual(len(sink.rows), 2)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = ManualClock()
        self.transport = RecordingTransport(self.clock)
        self.pusher: TelegramPusher | None = None

    def _pusher(self, cfg: PushSettings | None = None, *, testnet: bool = False) -> TelegramPusher:
        self.pusher = TelegramPusher(
            enabled=True,
            cfg=cfg or PushSettings(),
            transport=self.transport,
            clock=self.clock,
            testnet=testnet,
        )
        return self.pusher

    async def asyncTearDown(self) -> None:
        if self.pusher is not None:
            await self.pusher.stop()

    async def test_pace_is_one_a_second(self) -> None:
        pusher = self._pusher(PushSettings(max_per_min=20, repeat_s=0))
        await pusher.start()
        pusher.push("a", "a")
        pusher.push("b", "b")
        pusher.push("c", "c")
        await pusher.settle()
        times = [t for t, _text in self.transport.sent]
        self.assertEqual([text for _t, text in self.transport.sent], ["a", "b", "c"])
        self.assertAlmostEqual(times[1] - times[0], 1)
        self.assertAlmostEqual(times[2] - times[1], 1)

    async def test_429_waits_retry_after(self) -> None:
        self.transport.results = [SendResult(429, 3), SendResult(200)]
        pusher = self._pusher()
        start = self.clock.t
        await pusher.start()
        pusher.push("k", "hi")
        await pusher.settle()
        self.assertEqual(len(self.transport.sent), 2)
        self.assertAlmostEqual(self.clock.t - start, 3)

    async def test_three_failures_drop_and_push_does_not_raise(self) -> None:
        self.transport.results = [SendResult(500), SendResult(500), SendResult(500)]
        pusher = self._pusher()
        start = self.clock.t
        with self.assertLogs(level="DEBUG") as captured:
            await pusher.start()
            pusher.push("k", "hi")
            await pusher.settle()
        self.assertEqual(len(self.transport.sent), 3)
        self.assertAlmostEqual(self.clock.t - start, 14)
        dropped = [r for r in captured.records if "dropped" in r.getMessage()]
        self.assertEqual(len(dropped), 1)

    async def test_dedupe_and_urgent_skips_it(self) -> None:
        pusher = self._pusher(PushSettings(repeat_s=600, max_per_min=20))
        await pusher.start()
        pusher.push("k", "one")
        await pusher.settle()
        pusher.push("k", "two")
        await pusher.settle()
        self.assertEqual([text for _t, text in self.transport.sent], ["one"])
        pusher.push("k", "now", urgent=True)
        await pusher.settle()
        self.assertEqual([text for _t, text in self.transport.sent], ["one", "now"])
        self.clock.t += 601
        pusher.push("k", "later")
        await pusher.settle()
        self.assertEqual([text for _t, text in self.transport.sent], ["one", "now", "later"])

    async def test_urgent_jumps_the_queue_and_digest_holds_the_rest(self) -> None:
        pusher = self._pusher(PushSettings(max_per_min=2, repeat_s=0))
        await pusher.start()
        pusher.push("a", "a")
        pusher.push("b", "b")
        await pusher.settle()
        pusher.push("c", "c")
        pusher.push("u", "URGENT", urgent=True)
        await pusher.settle()
        texts = [text for _t, text in self.transport.sent]
        self.assertEqual(texts[:3], ["a", "b", "URGENT"])
        self.assertEqual(texts[3], "1 more: c")
        self.assertGreaterEqual(self.transport.sent[3][0] - self.transport.sent[0][0], 60)

    async def test_html_escape_truncation_and_testnet_prefix(self) -> None:
        pusher = self._pusher(PushSettings(max_per_min=20, repeat_s=0), testnet=True)
        await pusher.start()
        pusher.push("k", "a < b & c > d")
        pusher.push("t", "z" * 5000)
        await pusher.settle()
        first, second = (text for _t, text in self.transport.sent)
        self.assertEqual(first, "[testnet] a &lt; b &amp; c &gt; d")
        self.assertEqual(len(second), 4000)
        self.assertTrue(second.startswith("[testnet] "))

    async def test_disabled_makes_no_transport_calls(self) -> None:
        calls: list[str] = []

        class T:
            async def send_message(self, text: str) -> SendResult:
                calls.append(text)
                return SendResult(200)

        pusher = TelegramPusher(enabled=False, transport=T(), clock=self.clock)
        self.pusher = pusher
        await pusher.start()
        pusher.push("k", "hi")
        await pusher.settle()
        self.assertEqual(calls, [])

    async def test_token_never_appears_in_a_log_record(self) -> None:
        token = "super-secret-token"
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            return httpx.Response(500)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        transport = HttpxTransport(token, "4242424242", client)
        pusher = TelegramPusher(
            enabled=True,
            transport=transport,
            client=client,
            clock=self.clock,
            cfg=PushSettings(),
        )
        self.pusher = pusher
        with self.assertLogs(level="DEBUG") as captured:
            await pusher.start()
            self.assertEqual(logging.getLogger("httpx").level, logging.WARNING)
            self.assertEqual(logging.getLogger("httpcore").level, logging.WARNING)
            pusher.push("k", "hi")
            await pusher.settle()
        blob = "\n".join(r.getMessage() for r in captured.records)
        self.assertNotIn(token, blob)
        for rec in captured.records:
            self.assertNotIn(token, str(rec.args))
            if rec.exc_info and rec.exc_info[1] is not None:
                self.assertNotIn(token, str(rec.exc_info[1]))
        self.assertTrue(urls)
        self.assertTrue(all(token in url for url in urls))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    async def test_push_is_off_without_tokens(self, *_mocks: object) -> None:
        with (
            patch.object(settings, "telegram_bot_token", None),
            patch.object(settings, "telegram_chat_id", None),
        ):
            app = create_app()
            transport = ASGITransport(app=app)
            async with (
                app.router.lifespan_context(app),
                AsyncClient(transport=transport, base_url="http://localhost") as client,
            ):
                status = await client.get("/api/push")
                tested = await client.post("/api/push/test")
        self.assertEqual(status.status_code, 200)
        body = status.json()
        self.assertEqual(body["enabled"], False)
        self.assertNotIn("token", body)
        self.assertNotIn("chat_id", body)
        self.assertEqual(tested.json(), {"ok": False, "error": "Pushes are off"})

    @patch("mayedge.api.app.desk.start", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.restore", new_callable=AsyncMock)
    @patch("mayedge.api.app.desk.stop", new_callable=AsyncMock)
    async def test_test_push_and_status_hide_the_token(self, *_mocks: object) -> None:
        token = "super-secret-token"
        chat = "4242424242"
        clock = ManualClock()
        transport = RecordingTransport(clock)
        pusher = TelegramPusher(
            enabled=True,
            transport=transport,
            clock=clock,
            cfg=PushSettings(repeat_s=0, max_per_min=20),
        )
        with (
            patch.object(settings, "telegram_bot_token", token),
            patch.object(settings, "telegram_chat_id", chat),
            patch("mayedge.api.app.TelegramPusher.from_settings", return_value=pusher),
        ):
            app = create_app()
            http = ASGITransport(app=app)
            async with (
                app.router.lifespan_context(app),
                AsyncClient(transport=http, base_url="http://localhost") as client,
            ):
                status = await client.get("/api/push")
                tested = await client.post("/api/push/test")
        self.assertNotIn(token, status.text)
        self.assertNotIn(chat, status.text)
        self.assertTrue(status.json()["enabled"])
        self.assertEqual(tested.json(), {"ok": True})
        self.assertIn("Desk test push ✓", [text for _t, text in transport.sent])


class PortfolioDayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = settings.db_path
        store.close_db()
        settings.db_path = str(Path(self.tmp.name) / "push.db")
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        store.close_db()
        settings.db_path = self.old

    def test_portfolio_day_totals_need_both_midnights(self) -> None:
        day_ms = 1_700_006_400_000  # 2023-11-15 00:00 UTC

        def bucket(ts_ms: int, trade: float, staking: float) -> tuple[int, dict[str, object]]:
            return ts_ms, {"timestamp": ts_ms // 1000, "trade_pnl": trade, "staking_pnl": staking}

        portfolio_put_buckets("1d", "pnl", [bucket(day_ms, 100.0, 50.0)])
        self.assertIsNone(portfolio_day_totals("2023-11-15"), "no bucket at the day's end yet")
        portfolio_put_buckets("1d", "pnl", [bucket(day_ms + 86_400_000, 480.0, 42.0)])
        self.assertEqual(
            portfolio_day_totals("2023-11-15"), {"perps": 380.0, "spot": 0.0, "llp": 0.0, "staking": -8.0}
        )
        self.assertIsNone(portfolio_day_totals("2023-11-14"), "no bucket at that day's start")
