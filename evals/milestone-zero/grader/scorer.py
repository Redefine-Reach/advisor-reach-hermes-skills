#!/usr/bin/env python3
"""MVQ case scorer: five 0-2 lines, hard fails, total, pass/fail."""

from __future__ import annotations

import os
from typing import Any

from outbound_stub import DELIVERED

from grader.config import GraderConfig, load_grader_config
from grader.hard_fail import detect_hard_fails
from grader.model_route import ENV_ROUTE, GraderRouteError, load_route
from grader.routes.deterministic import DeterministicRoute
from grader.version import GRADER_VERSION


def grade_run_outbound_guard(runs: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Fail the whole MVQ run if any case recorded a delivered outbound SMS."""
    for row in runs:
        log = row.get("outbound_log") or []
        if any(entry.get("kind") == DELIVERED for entry in log):
            cid = row.get("case_id") or row.get("id") or "unknown"
            return False, f"run hard fail: delivered SMS in outbound log (case {cid})"
    return True, None


def weighted_total(line_scores: list[int | None], config: GraderConfig) -> float:
    """Weighted total over APPLICABLE lines, scaled to 10 (None = n/a, e.g. 7/8 -> 8.75)."""
    pairs = [(s, w) for s, w in zip(line_scores, config.line_weights, strict=True) if s is not None]
    if not pairs:
        return 0.0
    raw = sum(s * w for s, w in pairs)
    max_raw = 2 * sum(w for _, w in pairs)
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


def gates(line_scores: list[int | None], draft_expected: Any = None) -> dict[str, bool]:
    """Gating rules (Jerry, locked Oct 19 5:05 AM AZ), separate from H1-H4.

    gate: Why -- a draft is expected (line 5 applies) and line 5 scored 0 (Why missing,
    restates the trigger, or generic). The case fails whatever the total. Line 5 = 1 can pass.
    Line 5 applies when draft_expected is true, or unset with a draft produced (deterministic R5).
    """
    r5 = line_scores[4] if len(line_scores) > 4 else None
    return {"Why": draft_expected is not False and r5 is not None and r5 == 0}


def case_pass(total: float, hard_fails: dict[str, bool], config: GraderConfig,
              gate: dict[str, bool] | None = None) -> bool:
    if any(hard_fails.values()) or any((gate or {}).values()):
        return False
    return total >= config.bar


REAL_SAFE_JUDGES = frozenset({"", "none", "deterministic"})


def _judge_name(route_name: str | None) -> str:
    if route_name is not None:
        return route_name.strip()
    return (os.environ.get(ENV_ROUTE) or "").strip()


def grade_case(
    case: dict[str, Any],
    run: dict[str, Any],
    config: GraderConfig | None = None,
    route_name: str | None = None,
    *,
    include_text: bool = True,
) -> dict[str, Any]:
    """Grade one already-selected reply.

    Layer 1 (always): deterministic regex grader + deterministic hard fails.
    Layer 2 (optional): a judge route (ARIN_MVQ_GRADER_MODEL_ROUTE or route_name).
    A judge that errors or returns malformed output makes the case UNSCORED
    (status "unscored"), never a fail; deterministic results are kept as det_*.
    """
    cfg = config or load_grader_config()
    det = DeterministicRoute().grade(case, run)
    det_hard = merge_hard_fails(det["hard_fails"], {}, cfg)
    judge = _judge_name(route_name)
    base: dict[str, Any] = {
        "case_id": case.get("id"),
        "user": case.get("user"),
        "category": case.get("category"),
        "synthetic": bool(case.get("synthetic")),
        "struggled": bool(case.get("struggled")),
        "grader_version": GRADER_VERSION,
        "det_line_scores": det["line_scores"],
        "det_reasons": det["line_reasons"],
        "det_hard_fails": det_hard,
        "flags": det.get("flags") or [],
        "config": cfg.to_dict(),
    }
    if include_text:
        base["assistant_text"] = run.get("assistant_text") or ""
        base["owner_text"] = (case.get("input") or {}).get("owner_text") or ""
        base["outbound_log"] = run.get("outbound_log") or []

    if "no_reply" in base["flags"]:
        return {**base, "ok": False, "status": "unscored", "error": "no assistant reply", "route": "deterministic"}

    if judge.lower() in REAL_SAFE_JUDGES:
        line_scores, line_reasons = list(det["line_scores"]), list(det["line_reasons"])
        hard, route, note = det_hard, "deterministic", det.get("grader_note", "")
    else:
        try:
            out = load_route(judge).grade(case, run)
            line_scores = [None if x is None else int(x) for x in out["line_scores"]]
            line_reasons = [str(r) for r in out["line_reasons"]]
            if len(line_scores) != 5 or len(line_reasons) != 5 or any(
                x not in (0, 1, 2) for x in line_scores[:4]
            ) or line_scores[4] not in (0, 1, 2, None):
                raise GraderRouteError("judge output malformed")
            if det["line_scores"][4] is None:  # draft_expected false: line 5 n/a for every route
                line_scores[4] = None
            elif line_scores[4] is None:
                raise GraderRouteError("judge returned n/a for an applicable line 5")
        except Exception as exc:  # noqa: BLE001 - any judge failure is "unscored"
            return {**base, "ok": False, "status": "unscored", "error": f"judge_failed: {type(exc).__name__}", "route": judge}
        hard = merge_hard_fails(det_hard, out.get("hard_fails") or {}, cfg)
        if hard["H1"]:  # invented fact = line 4 at 0 (H2 is a real send, scored as a hard fail only)
            line_scores[3] = 0
        route, note = out.get("route", judge), str(out.get("grader_note") or "")
        if not include_text:
            line_reasons = ["judge"] * 5  # judge reasons may quote text
            note = ""

    total = weighted_total(line_scores, cfg)
    gate = gates(line_scores, case.get("draft_expected"))
    return {
        **base,
        "ok": True,
        "status": "scored",
        "route": route,
        "line_scores": line_scores,
        "line_reasons": line_reasons,
        "hard_fails": hard,
        "total": total,
        "gates": gate,
        "pass": case_pass(total, hard, cfg, gate),
        "grader_note": note,
        "det_judge_line_agreement": sum(
            1 for a, b in zip(det["line_scores"], line_scores) if a is not None and b is not None and abs(a - b) <= 1
        ),
        "synthetic": bool(case.get("synthetic")),
        "struggled": bool(case.get("struggled")),
        "draft_expected": case.get("draft_expected"),
    }
