from __future__ import annotations

from typing import Any

WAF_MSG = "Lighter blocked this IP (WAF captcha). Wait a minute — too many REST calls."
RATE_MSG = "Lighter rate limit — retry shortly"


class VenueBlocked(Exception):
    """Lighter REST/WAF refused the call. ``status`` is the HTTP code to surface."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def venue_client_error(err: Any) -> tuple[int, str] | None:
    """Map Lighter/CloudFront failures to an HTTP status + short message."""
    text = str(err or "")
    low = text.lower()
    if (
        "x-amzn-waf-action" in low
        or "human verification" in low
        or "captcha" in low
        or ("405" in text and "not allowed" in low)
    ):
        return 429, WAF_MSG
    if "429" in text or "23000" in text or "too many requests" in low or "rate limit" in low or "ratelimit" in low:
        return 429, RATE_MSG
    return None
