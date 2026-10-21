from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

WAF_MSG = "Lighter blocked this IP (WAF captcha). Wait a minute — too many REST calls."
RATE_MSG = "Lighter rate limit — retry shortly"


class Reject(StrEnum):
    """Why a send was refused. Precedence is the Errors table in lighter-limits.md."""

    BLOCKED = "blocked"
    INVALID_NONCE = "invalid_nonce"
    ORDER_NOT_FOUND = "order_not_found"
    MIN_SIZE = "min_size"
    WOULD_CROSS = "would_cross"
    ORDER_CAP = "order_cap"
    ORDER_EXPIRY = "order_expiry"
    DUPLICATE_COI = "duplicate_coi"


class VenueReject(ValueError):
    """A send Lighter refused. ``str()`` is the operator's message; ``reason`` is for code."""

    def __init__(self, reason: Reject, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.code = code


class VenueBlocked(Exception):
    """Lighter REST/WAF refused the call. ``status`` is the HTTP code to surface."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# Codes before the 2170x family, so 21701 and 21706 are never would-cross.
_CODE_REASONS: tuple[tuple[str, Reject], ...] = (
    ("21104", Reject.INVALID_NONCE),
    ("21706", Reject.MIN_SIZE),
    ("21701", Reject.ORDER_NOT_FOUND),
    ("21717", Reject.ORDER_CAP),
    ("21718", Reject.ORDER_CAP),
    ("21719", Reject.ORDER_CAP),
    ("21720", Reject.ORDER_CAP),
    ("21711", Reject.ORDER_EXPIRY),
    ("21728", Reject.DUPLICATE_COI),
)
# Exact phrases only. Bare "post", "cross", and "min " are not reasons.
_PHRASES: tuple[tuple[str, Reject], ...] = (
    ("invalid nonce", Reject.INVALID_NONCE),
    ("order not found", Reject.ORDER_NOT_FOUND),
    ("base or quote amount", Reject.MIN_SIZE),
    ("post-only", Reject.WOULD_CROSS),
    ("would cross", Reject.WOULD_CROSS),
)


def _is_http_error(err: BaseException) -> bool:
    """ApiException-shaped: status and body, plus headers that must not be read."""
    return hasattr(err, "body") or hasattr(err, "headers")


def _body_text(err: BaseException) -> str:
    body = getattr(err, "body", None)
    data = getattr(err, "data", None)
    text = body if isinstance(body, str) and body else ("" if data is None else str(data))
    status = getattr(err, "status", None)
    if isinstance(status, int):
        return f"({status}) {text}"
    return text


def _scan_text(err: object) -> str:
    if isinstance(err, BaseException) and _is_http_error(err):
        return _body_text(err)
    return str(err or "")


def code_of(err: object) -> int | None:
    """First Lighter code in ``err``, ignoring headers on an HTTP error."""
    text = _scan_text(err)
    for code, _reason in _CODE_REASONS:
        if has_code(text, code):
            return int(code)
    found = re.search(r"(?<![\d.])(2170\d)(?!\d|\.\d)", text)
    if found and found.group(1) not in {"21701", "21706"}:
        return int(found.group(1))
    if has_code(text, "23000"):
        return 23000
    if has_code(text, "429"):
        return 429
    return None


def _from_text(text: str) -> Reject | None:
    for code, reason in _CODE_REASONS:
        if has_code(text, code):
            return reason
    if has_code_prefix(text, "2170"):
        return Reject.WOULD_CROSS
    low = text.lower()
    for phrase, reason in _PHRASES:
        if phrase in low:
            return reason
    if venue_client_error(text):
        return Reject.BLOCKED
    return None


def is_blocked(err: object) -> bool:
    return reject_reason(err) is Reject.BLOCKED


def is_invalid_nonce(err: object) -> bool:
    return reject_reason(err) is Reject.INVALID_NONCE


def is_order_not_found(err: object) -> bool:
    return reject_reason(err) is Reject.ORDER_NOT_FOUND


def is_min_size(err: object) -> bool:
    return reject_reason(err) is Reject.MIN_SIZE


def is_would_cross(err: object) -> bool:
    return reject_reason(err) is Reject.WOULD_CROSS


def reject_reason(err: object) -> Reject | None:
    """The one place a venue failure is classified. Order follows lighter-limits.md."""
    if isinstance(err, VenueReject):
        return err.reason
    if isinstance(err, BaseException):
        from mayedge.lighter.budget import BudgetRefused

        if isinstance(err, BudgetRefused):
            return None
        if _is_http_error(err):
            if getattr(err, "status", None) == 429:
                return Reject.BLOCKED
            return _from_text(_body_text(err))
        if isinstance(err, VenueBlocked):
            return Reject.BLOCKED
    if err is None or err == "":
        return None
    return _from_text(str(err))


def has_code(text: Any, code: str) -> bool:
    """True when ``code`` stands alone in ``text``, not inside a longer number.

    ``429`` matches ``(429)`` and ``code=429``. It does not match ``64290.5``,
    ``0.0429``, or an order index that happens to contain those digits.
    """
    return re.search(rf"(?<![\d.]){re.escape(code)}(?!\d|\.\d)", str(text or "")) is not None


def has_code_prefix(text: Any, prefix: str) -> bool:
    """True when a code of ``prefix`` plus one digit stands alone in ``text``."""
    return re.search(rf"(?<![\d.]){re.escape(prefix)}\d(?!\d|\.\d)", str(text or "")) is not None


def venue_client_error(err: Any) -> tuple[int, str] | None:
    """Map Lighter/CloudFront failures to an HTTP status + short message."""
    text = str(err or "")
    low = text.lower()
    if (
        "x-amzn-waf-action" in low
        or "human verification" in low
        or "captcha" in low
        or (has_code(text, "405") and "not allowed" in low)
    ):
        return 429, WAF_MSG
    if (
        has_code(text, "429")
        or has_code(text, "23000")
        or "too many requests" in low
        or "rate limit" in low
        or "ratelimit" in low
    ):
        return 429, RATE_MSG
    return None


def http_block(status: int, body: str) -> tuple[int, str] | None:
    """Classify a raw HTTP response. A 200 is never a block, whatever its body holds."""
    if status == 200:
        return None
    if status == 429:
        return 429, RATE_MSG
    return venue_client_error(f"({status}) {body}")


_DOWN_HTTP = frozenset({502, 503, 504})
# 1012 service restart, 1013 try again later: Lighter is going away, not us.
_DOWN_CLOSE = {1012: "service restart", 1013: "try again later"}


def venue_down_reason(err: BaseException | None) -> str | None:
    """Short reason when ``err`` says Lighter itself is offline (maintenance, restart).

    Looks through exception groups and chained causes, since sockets fail inside TaskGroups.
    """
    seen: set[int] = set()
    stack: list[BaseException] = [err] if err is not None else []
    while stack:
        e = stack.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        response = getattr(e, "response", None)
        status = getattr(response, "status_code", None) or getattr(e, "status", None)
        if isinstance(status, int) and status in _DOWN_HTTP:
            return f"HTTP {status}"
        rcvd = getattr(e, "rcvd", None)
        code = getattr(rcvd, "code", None)
        if isinstance(code, int) and code in _DOWN_CLOSE:
            return f"{code} {_DOWN_CLOSE[code]}"
        if isinstance(e, BaseExceptionGroup):
            stack.extend(e.exceptions)
        for nxt in (e.__cause__, e.__context__):
            if nxt is not None:
                stack.append(nxt)
    return None
