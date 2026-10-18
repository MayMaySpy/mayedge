import unittest

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.frames import Close
from websockets.http11 import Response

from mayedge import feed_health
from mayedge.lighter.errors import venue_down_reason


def _status(code: int) -> InvalidStatus:
    return InvalidStatus(Response(code, "x", Headers()))


def _closed(code: int) -> ConnectionClosedError:
    return ConnectionClosedError(Close(code, "server shutting down"), None)


class VenueDownReasonTest(unittest.TestCase):
    def test_handshake_503_is_down(self) -> None:
        self.assertEqual(venue_down_reason(_status(503)), "HTTP 503")

    def test_handshake_429_is_not_down(self) -> None:
        self.assertIsNone(venue_down_reason(_status(429)))

    def test_service_restart_close_is_down(self) -> None:
        self.assertEqual(venue_down_reason(_closed(1012)), "1012 service restart")

    def test_normal_close_is_not_down(self) -> None:
        self.assertIsNone(venue_down_reason(_closed(1006)))

    def test_found_inside_exception_group(self) -> None:
        group = ExceptionGroup("tg", [ValueError("x"), _closed(1012)])
        self.assertEqual(venue_down_reason(group), "1012 service restart")

    def test_rest_service_exception_status(self) -> None:
        class ServiceException(Exception):
            status = 503

        self.assertEqual(venue_down_reason(ServiceException("(503)")), "HTTP 503")

    def test_plain_error_is_not_down(self) -> None:
        self.assertIsNone(venue_down_reason(RuntimeError("boom")))


class VenueDownHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[dict[str, object]] = []
        feed_health.set_emitter(self.sent.append)
        feed_health.set_market_ws("live", broadcast=False)

    def tearDown(self) -> None:
        feed_health.set_emitter(None)

    def test_since_is_kept_across_retries_and_cleared_by_a_message(self) -> None:
        feed_health.set_market_ws("reconnecting", broadcast=False)
        feed_health.note_venue_down("HTTP 503")
        since = feed_health.snapshot()["venue_down_since"]
        self.assertGreater(since, 0)
        sent = len(self.sent)
        feed_health.note_venue_down("HTTP 503")
        self.assertEqual(feed_health.snapshot()["venue_down_since"], since)
        self.assertEqual(len(self.sent), sent, "same reason should not rebroadcast")
        feed_health.touch_market_msg()
        snap = feed_health.snapshot()
        self.assertEqual(snap["venue_down_since"], 0)
        self.assertIsNone(snap["venue_down_reason"])
        self.assertEqual(self.sent[-1]["venue_down_since"], 0)


if __name__ == "__main__":
    unittest.main()
