"""One classification for a venue reject. The table is docs/lighter-limits.md."""

from __future__ import annotations

import unittest

from lighter.exceptions import ApiException
from urllib3 import HTTPHeaderDict

from mayedge.lighter.budget import BudgetRefused
from mayedge.lighter.errors import (
    RATE_MSG,
    Reject,
    VenueBlocked,
    VenueReject,
    reject_reason,
)

_HEADER = {
    "Access-Control-Allow-Methods": "GET, POST",
    "Access-Control-Allow-Origin": "https://cross-origin.example",
}


def _http(status: int, body: str) -> ApiException:
    err = ApiException(status=status, reason="Bad Request", body=body)
    err.headers = _HEADER
    return err


class _Resp:
    """Just enough of a urllib3 response for ApiException to read status, reason and headers."""

    def __init__(self, status: int, reason: str, headers: dict[str, str], body: str) -> None:
        self.status = status
        self.reason = reason
        self.data = body.encode()
        self._headers = HTTPHeaderDict(headers)

    def getheaders(self) -> HTTPHeaderDict:
        return self._headers


def _sdk(status: int, reason: str, headers: dict[str, str], body: str = "") -> ApiException:
    """An ApiException built the way the SDK builds one, from the response."""
    return ApiException(http_resp=_Resp(status, reason, headers, body), body=body)


class RejectReasonTests(unittest.TestCase):
    def test_blocked(self) -> None:
        for err in (
            _http(429, "invalid nonce"),
            _http(400, '{"code":23000,"message":"Too Many Requests!"}'),
            _http(405, "<title>405 Not Allowed</title> human verification"),
            VenueBlocked(429, RATE_MSG),
            RuntimeError("429 too many requests"),
            "code=23000 message='ratelimit'",
        ):
            self.assertIs(reject_reason(err), Reject.BLOCKED, err)
        self.assertIsNone(reject_reason(BudgetRefused(429, "local")))

    def test_waf_is_blocked(self) -> None:
        """The WAF header and the HTTP reason are read; no other header is."""
        for err in (
            _sdk(405, "Not Allowed", {"x-amzn-waf-action": "captcha", **_HEADER}),
            _sdk(405, "Not Allowed", {}, "<html><script src='challenge.js'></script></html>"),
            _sdk(403, "Forbidden", {"X-Amzn-Waf-Action": "block"}, "Request blocked."),
            _sdk(
                403,
                "Forbidden",
                {"x-amzn-waf-action": "captcha"},
                '{"code":21104,"message":"invalid nonce"}',
            ),
        ):
            self.assertIs(reject_reason(err), Reject.BLOCKED, err)

    def test_other_headers_are_not_read(self) -> None:
        exposed = {"Access-Control-Expose-Headers": "x-amzn-waf-action, too many requests"}
        self.assertIsNone(reject_reason(_sdk(403, "Forbidden", exposed)))
        nonce = _sdk(400, "Bad Request", exposed, '{"code":21104,"message":"invalid nonce"}')
        self.assertIs(reject_reason(nonce), Reject.INVALID_NONCE)

    def test_blocked_comes_first(self) -> None:
        for err in (
            "code=21702 rate limit",
            "invalid nonce: too many requests",
            RuntimeError("order not found (429)"),
            _http(400, '{"code":23000,"message":"post-only would cross"}'),
        ):
            self.assertIs(reject_reason(err), Reject.BLOCKED, err)

    def test_invalid_nonce(self) -> None:
        poisoned = _http(400, '{"code":21104,"message":"invalid nonce"}')
        self.assertIn("POST", str(poisoned))
        self.assertIn("cross-origin", str(poisoned))
        for err in (
            poisoned,
            RuntimeError("HTTP response body: code=21104 message='invalid nonce'"),
            "invalid nonce",
            21104,
        ):
            self.assertIs(reject_reason(err), Reject.INVALID_NONCE, err)

    def test_order_not_found(self) -> None:
        for err in (
            RuntimeError("order not found (21701)"),
            "order not found",
            21701,
        ):
            self.assertIs(reject_reason(err), Reject.ORDER_NOT_FOUND, err)
            self.assertIsNot(reject_reason(err), Reject.WOULD_CROSS, err)
        self.assertIsNone(reject_reason("404 Not Found"))

    def test_min_size(self) -> None:
        coded = "invalid order base or quote amount (code 21706)"
        self.assertIs(reject_reason(coded), Reject.MIN_SIZE)
        self.assertIs(reject_reason("invalid order base or quote amount"), Reject.MIN_SIZE)
        self.assertIsNone(reject_reason("Min 0.01 ETH or $10"))
        self.assertIsNot(reject_reason(21706), Reject.WOULD_CROSS)
        kept = VenueReject(Reject.MIN_SIZE, "Min 0.01 ETH or $10", 21706)
        self.assertIs(reject_reason(kept), Reject.MIN_SIZE)

    def test_order_cap(self) -> None:
        for code, message in (
            (21717, "Account order cap reached"),
            (21718, "Per-market order cap reached"),
            (21719, "Pending order cap reached"),
            (21720, "Pending order cap reached"),
        ):
            self.assertIs(reject_reason(f"code={code} {message}"), Reject.ORDER_CAP, code)

    def test_order_expiry(self) -> None:
        self.assertIs(reject_reason("code=21711 invalid expiry"), Reject.ORDER_EXPIRY)

    def test_duplicate_coi(self) -> None:
        self.assertIs(
            reject_reason("code=21728 client order index already exists"),
            Reject.DUPLICATE_COI,
        )

    def test_would_cross(self) -> None:
        for err in (
            RuntimeError("code=21702 would cross"),
            RuntimeError("rejected (21702)"),
            RuntimeError("post-only order would cross"),
            "post-only",
            "post only order rejected",
            "PostOnly order would take liquidity",
            "POST_ONLY",
            "would cross",
            21700,
            21709,
        ):
            self.assertIs(reject_reason(err), Reject.WOULD_CROSS, err)
        for err in (
            RuntimeError("order 82170 rejected at 121705.5"),
            "order price 64290.5 is too far from mark",
            "order 8000021706 rejected",
            "Access-Control-Allow-Methods: GET, POST",
            "POST https://mainnet.zklighter.elliot.ai/api/v1/sendTx only failed",
            "cross-origin",
            21701,
            21706,
        ):
            self.assertIsNot(reject_reason(err), Reject.WOULD_CROSS, err)

    def test_venue_reject_keeps_its_reason(self) -> None:
        err = VenueReject(Reject.INVALID_NONCE, "Min 0.01 ETH or $10", 21104)
        self.assertEqual(str(err), "Min 0.01 ETH or $10")
        try:
            raise err
        except ValueError as caught:
            self.assertIs(reject_reason(caught), Reject.INVALID_NONCE)
            self.assertIs(caught, err)
