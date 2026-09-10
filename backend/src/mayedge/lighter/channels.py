from __future__ import annotations

from typing import Any

_FE_SUFFIX = "_fe"
_WS_ACTIONS = frozenset({"subscribed", "update"})


def normalize_channel_kind(kind: str) -> str:
    """Strip the frontend ``_fe`` suffix: ``trade_fe`` → ``trade``."""
    text = kind.strip()
    if text.endswith(_FE_SUFFIX) and len(text) > len(_FE_SUFFIX):
        return text[: -len(_FE_SUFFIX)]
    return text


def split_ws_type(msg_type: Any) -> tuple[str, str]:
    """``('subscribed'|'update'|'', kind)`` with ``_fe`` stripped from kind."""
    raw = str(msg_type or "").strip()
    action, sep, rest = raw.partition("/")
    if not sep:
        return "", normalize_channel_kind(action.split(":")[0].split("@")[0])
    kind = normalize_channel_kind(rest.split(":")[0].split("/")[0].split("@")[0])
    if action not in _WS_ACTIONS:
        return "", kind
    return action, kind


def _int_token(token: str) -> int | None:
    text = token.strip()
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    return None


def parse_channel_market(channel: Any, *kinds: str) -> int | None:
    """Market index from channels like ``trade_fe/120`` or ``order_book@tier2/120``.

    ``kinds`` match the public name or the official ``*_fe`` / ``@tier`` forms.
    Unparsed input is ``None`` — never guess the desk's current market.
    """
    if isinstance(channel, bool):
        return None
    if isinstance(channel, int):
        return channel
    if isinstance(channel, float) and channel.is_integer():
        return int(channel)
    if not isinstance(channel, str) or not channel:
        return None

    parts = channel.replace(":", "/").split("/")
    head = parts[0].strip()
    base = normalize_channel_kind(head.split("@")[0])
    if kinds:
        wanted = {normalize_channel_kind(kind) for kind in kinds if kind}
        if base not in wanted:
            return None
    for part in parts[1:]:
        parsed = _int_token(part)
        if parsed is not None:
            return parsed
    return _int_token(head)


def message_market_index(msg: dict[str, Any], *kinds: str) -> int | None:
    idx = parse_channel_market(msg.get("channel"), *kinds)
    if idx is not None:
        return idx
    for key in ("market_id", "market_index"):
        raw = msg.get(key)
        if raw is None:
            continue
        parsed = parse_channel_market(raw)
        if parsed is not None:
            return parsed
    return None
