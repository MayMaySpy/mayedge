"""The alerts: knobs of alerts.yaml. Every threshold is in docs/alert-rules.md."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from mayedge.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AlertSettings:
    min_24h_usd: float = 1_000_000.0
    max_spread_bps: float = 40.0
    spike_window_min: int = 60
    spike_price_x: float = 2.0
    spike_volume_x: float = 3.0
    spike_oi_x: float = 2.0
    spike_min_move_pct: float = 0.25
    spike_min_volume_usd: float = 50_000.0
    spike_min_oi_usd: float = 250_000.0
    spike_min_oi_pct: float = 0.3
    liq_oi_bps: float = 20.0
    liq_min_usd: float = 100_000.0
    liq_window_s: float = 120.0
    board_move_pct: float = 0.3
    board_min_movers: int = 10
    board_agree: float = 0.8
    board_median_pct: float = 0.5
    held_liq_distance_pct: float = 10.0
    funding_sigma: float = 3.0
    funding_sigma_floor: float = 0.002
    funding_retention_days: int = 30
    merge_s: float = 120.0
    quiet_s: float = 180.0
    max_new_per_min: int = 6
    log_retention_days: int = 90
    range_floor_pct: float = 3.0
    bars_1m: int = 240
    min_bars: int = 30
    level_window_min: int = 1440
    level_min_samples: int = 30
    horizon_min: int = 15
    retention_days: int = 30


def _f(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def thresholds_from_dict(data: dict[str, Any] | None) -> AlertSettings:
    d = data or {}
    base = AlertSettings()
    liquidity = d.get("liquidity") or {}
    spike = d.get("spike") or {}
    liqs = d.get("liquidations") or {}
    board = d.get("board") or {}
    held = d.get("held") or {}
    funding = d.get("funding") or {}
    rows = d.get("rows") or {}
    activity = d.get("activity") or {}
    baseline = d.get("baseline") or {}
    outcomes = d.get("outcomes") or {}
    return AlertSettings(
        min_24h_usd=_f(liquidity.get("min_24h_usd"), base.min_24h_usd),
        max_spread_bps=_f(liquidity.get("max_spread_bps"), base.max_spread_bps),
        spike_window_min=int(_f(spike.get("window_min"), base.spike_window_min)),
        spike_price_x=_f(spike.get("price_x"), base.spike_price_x),
        spike_volume_x=_f(spike.get("volume_x"), base.spike_volume_x),
        spike_oi_x=_f(spike.get("oi_x"), base.spike_oi_x),
        spike_min_move_pct=_f(spike.get("min_move_pct"), base.spike_min_move_pct),
        spike_min_volume_usd=_f(spike.get("min_volume_usd"), base.spike_min_volume_usd),
        spike_min_oi_usd=_f(spike.get("min_oi_usd"), base.spike_min_oi_usd),
        spike_min_oi_pct=_f(spike.get("min_oi_pct"), base.spike_min_oi_pct),
        liq_oi_bps=_f(liqs.get("oi_bps"), base.liq_oi_bps),
        liq_min_usd=_f(liqs.get("min_usd"), base.liq_min_usd),
        liq_window_s=_f(liqs.get("window_s"), base.liq_window_s),
        board_move_pct=_f(board.get("move_pct"), base.board_move_pct),
        board_min_movers=int(_f(board.get("min_movers"), base.board_min_movers)),
        board_agree=_f(board.get("agree"), base.board_agree),
        board_median_pct=_f(board.get("median_pct"), base.board_median_pct),
        held_liq_distance_pct=_f(held.get("liq_distance_pct"), base.held_liq_distance_pct),
        funding_sigma=_f(funding.get("sigma"), base.funding_sigma),
        funding_sigma_floor=_f(funding.get("sigma_floor"), base.funding_sigma_floor),
        funding_retention_days=int(_f(funding.get("retention_days"), base.funding_retention_days)),
        merge_s=_f(rows.get("merge_s"), base.merge_s),
        quiet_s=_f(rows.get("quiet_s"), base.quiet_s),
        max_new_per_min=int(_f(rows.get("max_new_per_min"), base.max_new_per_min)),
        log_retention_days=int(_f(rows.get("log_retention_days"), base.log_retention_days)),
        range_floor_pct=_f(activity.get("range_floor_pct"), base.range_floor_pct),
        bars_1m=int(_f(baseline.get("bars_1m"), base.bars_1m)),
        min_bars=int(_f(baseline.get("min_bars"), base.min_bars)),
        level_window_min=int(_f(baseline.get("level_window_min"), base.level_window_min)),
        level_min_samples=int(_f(baseline.get("level_min_samples"), base.level_min_samples)),
        horizon_min=int(_f(outcomes.get("horizon_min"), base.horizon_min)),
        retention_days=int(_f(outcomes.get("retention_days"), base.retention_days)),
    )


def resolve_alerts_config_path() -> Path:
    return Path(settings.alerts_config)


def load_thresholds(path: Path | None = None) -> AlertSettings:
    p = path or resolve_alerts_config_path()
    if not p.is_file():
        logger.warning("alerts yaml missing at %s; using defaults", p)
        return AlertSettings()
    try:
        data = yaml.safe_load(p.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError("root must be a mapping")
        thr = thresholds_from_dict(data)
        logger.info("loaded alert thresholds from %s", p)
        return thr
    except Exception:
        logger.exception("failed to parse %s; using defaults", p)
        return AlertSettings()
