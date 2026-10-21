from __future__ import annotations

import re
from typing import Any

WAF_MSG = "Lighter blocked this IP (WAF captcha). Wait a minute — too many REST calls."
RATE_MSG = "Lighter rate limit — retry shortly"


class VenueBlocked(Exception):
    """Lighter REST/WAF refused the call. ``status`` is the HTTP code to surface."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


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
