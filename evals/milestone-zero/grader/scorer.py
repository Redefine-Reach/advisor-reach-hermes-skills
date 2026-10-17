#!/usr/bin/env python3
"""MVQ case scorer: five 0-2 lines, hard fails, total, pass/fail."""

from __future__ import annotations

from typing import Any

from outbound_stub import DELIVERED

from grader.config import GraderConfig, load_grader_config
from grader.hard_fail import detect_hard_fails
from grader.model_route import GraderRouteError, load_route
from grader.version import GRADER_VERSION


def grade_run_outbound_guard(runs: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Fail the whole MVQ run if any case recorded a delivered outbound SMS."""
    for row in runs:
        log = row.get("outbound_log") or []
        if any(entry.get("kind") == DELIVERED for entry in log):
            cid = row.get("case_id") or row.get("id") or "unknown"
            return False, f"run hard fail: delivered SMS in outbound log (case {cid})"
    return True, None


def weighted_total(line_scores: list[int], config: GraderConfig) -> float:
    weights = config.line_weights
    raw = sum(s * w for s, w in zip(line_scores, weights, strict=True))
    max_raw = 2 * sum(weights)
    return round((raw / max_raw) * 10, 2)


def merge_hard_fails(
    deterministic: dict[str, bool],
    model: dict[str, bool],
    config: GraderConfig,
) -> dict[str, bool]:
    merged: dict[str, bool] = {}
    for key in ("H1", "H2", "H3", "H4"):
        value = bool(deterministic.get(key)) or bool(model.get(key))
        if key not in config.enabled_hard_fails:
            value = False
        merged[key] = value
    return merged


def case_pass(total: float, hard_fails: dict[str, bool], config: GraderConfig) -> bool:
    if any(hard_fails.values()):
        return False
    return total >= config.bar


def grade_case(
    case: dict[str, Any],
    run: dict[str, Any],
    config: GraderConfig | None = None,
    route_name: str | None = None,
) -> dict[str, Any]:
    cfg = config or load_grader_config()
    det_hard = detect_hard_fails(case, run)
    try:
        route = load_route(route_name)
        model_out = route.grade(case, run)
    except GraderRouteError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "grader_version": GRADER_VERSION,
            "config": cfg.to_dict(),
        }

    line_scores = [int(x) for x in model_out["line_scores"]]
    line_reasons = list(model_out["line_reasons"])
    hard = merge_hard_fails(det_hard, model_out.get("hard_fails") or {}, cfg)
    total = weighted_total(line_scores, cfg)
    passed = case_pass(total, hard, cfg)

    return {
        "ok": True,
        "case_id": case.get("id"),
        "user": case.get("user"),
        "category": case.get("category"),
        "grader_version": GRADER_VERSION,
        "route": model_out.get("route"),
        "line_scores": line_scores,
        "line_reasons": line_reasons,
        "hard_fails": hard,
        "total": total,
        "pass": passed,
        "grader_note": model_out.get("grader_note", ""),
        "assistant_text": run.get("assistant_text") or "",
        "owner_text": (case.get("input") or {}).get("owner_text") or "",
        "outbound_log": run.get("outbound_log") or [],
        "config": cfg.to_dict(),
    }
