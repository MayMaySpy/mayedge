from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def fmt_decimal(d: Decimal | None) -> str | None:
    """Format a Decimal for APIs without stripping integer trailing zeros.

    ``210`` must stay ``\"210\"`` — a naive ``rstrip(\"0\")`` turns it into ``\"21\"``.
    Only fractional trailing zeros are removed (``3.50`` → ``\"3.5\"``).
    """
    if d is None:
        return None
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def check_notional(qty: Decimal, price: Decimal, cap: float | None) -> None:
    """Reject when qty * price exceeds cap. No-op when cap is unset or price unknown."""
    if cap is None or cap <= 0:
        return
    if price <= 0:
        return
    notional = float(qty * price)
    if notional > cap:
        raise ValueError(f"Order notional ${notional:,.0f} exceeds limit ${cap:,.0f}")


def parse_decimal(value: Any) -> Decimal:
    """Parse a trader-typed number. Comma or period may be the decimal.

    Last separator is the decimal; the other is treated as grouping.
    A single comma is a decimal (``0,5`` → ``0.5``). Grouped integers
    without a decimal (``1,000``) are not supported — type ``1000``.
    """
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("invalid number")
        return value
    if isinstance(value, bool):
        raise ValueError("invalid number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("invalid number")
        return Decimal(str(value))

    s = str(value).strip().replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    if not s:
        raise ValueError("empty number")
    if s[0] in "+-":
        sign, body = s[0], s[1:]
    else:
        sign, body = "", s
    if not body:
        raise ValueError(f"invalid number {value!r}")

    last_comma = body.rfind(",")
    last_dot = body.rfind(".")
    if last_comma >= 0 and last_dot >= 0:
        if last_comma > last_dot:
            body = body.replace(".", "").replace(",", ".")
        else:
            body = body.replace(",", "")
    elif last_comma >= 0:
        left, _, right = body.rpartition(",")
        body = left.replace(",", "") + "." + right

    try:
        d = Decimal(sign + body)
    except InvalidOperation as e:
        raise ValueError(f"invalid number {value!r}") from e
    if not d.is_finite():
        raise ValueError("invalid number")
    return d
