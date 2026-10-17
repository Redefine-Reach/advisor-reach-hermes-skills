"""Tuning knobs for MVQ grader (RED-681 §5)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_BAR = 8.0
DEFAULT_WEIGHTS = (1.0, 1.0, 1.0, 1.0, 1.0)
DEFAULT_ENABLED_HARD_FAILS = ("H1", "H2", "H3", "H4")


@dataclass(frozen=True)
class GraderConfig:
    bar: float = DEFAULT_BAR
    line_weights: tuple[float, ...] = DEFAULT_WEIGHTS
    enabled_hard_fails: frozenset[str] = frozenset(DEFAULT_ENABLED_HARD_FAILS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bar": self.bar,
            "line_weights": list(self.line_weights),
            "enabled_hard_fails": sorted(self.enabled_hard_fails),
        }


def _parse_weights(raw: str) -> tuple[float, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 5:
        raise ValueError("line_weights must have exactly 5 comma-separated numbers")
    return tuple(float(p) for p in parts)


def _parse_hard_fails(raw: str) -> frozenset[str]:
    items = {p.strip().upper() for p in raw.split(",") if p.strip()}
    allowed = {"H1", "H2", "H3", "H4"}
    bad = items - allowed
    if bad:
        raise ValueError(f"unknown hard-fail ids: {sorted(bad)}")
    return frozenset(items)


def load_grader_config(path: str | os.PathLike[str] | None = None) -> GraderConfig:
    """Load config from env, optional JSON file, then defaults."""
    bar = float(os.environ.get("ARIN_MVQ_GRADER_BAR", DEFAULT_BAR))
    weights = DEFAULT_WEIGHTS
    hard = frozenset(DEFAULT_ENABLED_HARD_FAILS)

    cfg_path = path or os.environ.get("ARIN_MVQ_GRADER_CONFIG")
    data: dict[str, Any] = {}
    if cfg_path:
        with open(cfg_path, encoding="utf-8") as handle:
            data = json.load(handle)
        bar = float(data.get("bar", bar))
        if "line_weights" in data:
            weights = tuple(float(x) for x in data["line_weights"])
        if "enabled_hard_fails" in data:
            hard = frozenset(str(x).upper() for x in data["enabled_hard_fails"])

    if os.environ.get("ARIN_MVQ_GRADER_LINE_WEIGHTS"):
        weights = _parse_weights(os.environ["ARIN_MVQ_GRADER_LINE_WEIGHTS"])
    if os.environ.get("ARIN_MVQ_GRADER_ENABLED_HARD_FAILS"):
        hard = _parse_hard_fails(os.environ["ARIN_MVQ_GRADER_ENABLED_HARD_FAILS"])

    if len(weights) != 5:
        raise ValueError("line_weights must have length 5")
    if any(w <= 0 for w in weights):
        raise ValueError("line_weights must be positive")

    return GraderConfig(bar=bar, line_weights=weights, enabled_hard_fails=hard)
