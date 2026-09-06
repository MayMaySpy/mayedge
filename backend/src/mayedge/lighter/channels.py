from __future__ import annotations

from typing import Any


def parse_channel_market(channel: Any, *kinds: str) -> int | None:
    """Market index from Lighter channels like ``trade:120`` or ``order_book/120``."""
    if isinstance(channel, bool):
        return None
    if isinstance(channel, int):
        return channel
    if isinstance(channel, float) and channel.is_integer():
        return int(channel)
    if not isinstance(channel, str) or not channel:
        return None
    raw = channel
    for kind in kinds:
        raw = raw.replace(f"{kind}:", "").replace(f"{kind}/", "")
    token = raw.split("/")[0].split(":")[0].strip()
    if token.isdigit() or (token.startswith("-") and token[1:].isdigit()):
        return int(token)
    return None


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
