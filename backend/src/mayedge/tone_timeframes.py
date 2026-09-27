"""Native timeframes a tone alert is allowed to follow."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mayedge.config import settings

logger = logging.getLogger(__name__)

NATIVE_TONE_TIMEFRAMES: tuple[str, ...] = (
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "12h",
    "1d",
)
TONE_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14_400,
    "12h": 43_200,
    "1d": 86_400,
}
TONE_TIMEFRAME_CAP = 2
DEFAULT_TONE_TIMEFRAMES: tuple[str, ...] = ("30m", "4h")


def tone_timeframes_path() -> Path:
    """Operator choice survives restart. Lives beside the database, not in git."""
    return Path(settings.db_path).resolve().parent / "tone_timeframes.json"


def normalize_tone_timeframes(raw: object) -> tuple[str, ...]:
    """Accept a list of native labels. Empty turns alerts off. At most two."""
    if not isinstance(raw, list):
        raise ValueError("timeframes must be a list")
    chosen: list[str] = []
    for item in raw:
        label = str(item).strip()
        if label not in TONE_TIMEFRAME_SECONDS:
            raise ValueError(f"unsupported timeframe: {label}")
        if label not in chosen:
            chosen.append(label)
    if len(chosen) > TONE_TIMEFRAME_CAP:
        raise ValueError("at most two timeframes")
    return tuple(chosen)


def load_tone_timeframes(path: Path | None = None) -> tuple[str, ...]:
    p = path or tone_timeframes_path()
    if not p.is_file():
        return DEFAULT_TONE_TIMEFRAMES
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            raise ValueError("root must be a mapping")
        return normalize_tone_timeframes(data.get("timeframes"))
    except Exception:
        logger.exception("failed to parse %s; using 30m and 4h", p)
        return DEFAULT_TONE_TIMEFRAMES


def save_tone_timeframes(labels: tuple[str, ...], path: Path | None = None) -> None:
    p = path or tone_timeframes_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timeframes": list(labels)}
    p.write_text(json.dumps(payload, indent=2) + "\n")


def candle_channel_resolution(channel: object) -> str | None:
    """Resolution token from ``candle/123/30m``. Unknown tokens are ignored."""
    if not isinstance(channel, str) or not channel:
        return None
    parts = [part for part in channel.replace(":", "/").split("/") if part]
    if len(parts) < 3:
        return None
    label = parts[-1].strip()
    if label in TONE_TIMEFRAME_SECONDS:
        return label
    return None
