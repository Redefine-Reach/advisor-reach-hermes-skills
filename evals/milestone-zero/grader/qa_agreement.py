#!/usr/bin/env python3
"""QA agreement: human vs grader scores (RED-681 §4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compare_samples(
    human: list[dict[str, Any]],
    grader: list[dict[str, Any]],
    *,
    line_tolerance: int = 1,
    line_target: float = 0.8,
    hard_target: float = 1.0,
) -> dict[str, Any]:
    human_by_id = {row["case_id"]: row for row in human}
    grader_by_id = {row["case_id"]: row for row in grader}
    ids = sorted(set(human_by_id) & set(grader_by_id))
    if not ids:
        return {
            "ok": False,
            "error": "no overlapping case_id between human and grader samples",
            "line_agreement_rate": 0.0,
            "hard_fail_agreement_rate": 0.0,
        }

    line_total = 0
    line_ok = 0
    hard_total = 0
    hard_ok = 0
    disagreements: list[str] = []

    for cid in ids:
        h = human_by_id[cid]
        g = grader_by_id[cid]
        h_scores = h.get("line_scores") or [0] * 5
        g_scores = g.get("line_scores") or [0] * 5
        for i in range(5):
            if h_scores[i] is None or g_scores[i] is None:
                continue  # n/a line (draft_expected false)
            line_total += 1
            if abs(int(h_scores[i]) - int(g_scores[i])) <= line_tolerance:
                line_ok += 1
            else:
                disagreements.append(
                    f"{cid} R{i+1}: human={h_scores[i]} grader={g_scores[i]}"
                )
        for key in ("H1", "H2", "H3", "H4"):
            hard_total += 1
            hv = bool((h.get("hard_fails") or {}).get(key))
            gv = bool((g.get("hard_fails") or {}).get(key))
            if hv == gv:
                hard_ok += 1
            else:
                disagreements.append(f"{cid} {key}: human={hv} grader={gv}")

    line_rate = line_ok / line_total if line_total else 0.0
    hard_rate = hard_ok / hard_total if hard_total else 0.0
    ok = line_rate >= line_target and hard_rate >= hard_target
    return {
        "ok": ok,
        "cases_compared": len(ids),
        "line_agreement_rate": line_rate,
        "hard_fail_agreement_rate": hard_rate,
        "line_target": line_target,
        "hard_target": hard_target,
        "disagreements": disagreements,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MVQ QA agreement checker")
    parser.add_argument("--human", required=True, type=Path, help="JSON list of human-scored cases")
    parser.add_argument("--grader", required=True, type=Path, help="JSON list of grader-scored cases")
    parser.add_argument("--line-target", type=float, default=0.8)
    parser.add_argument("--hard-target", type=float, default=1.0)
    args = parser.parse_args(argv)

    human = json.loads(args.human.read_text(encoding="utf-8"))
    grader_raw = json.loads(args.grader.read_text(encoding="utf-8"))
    if isinstance(grader_raw, dict) and "cases" in grader_raw:
        grader = [c for c in grader_raw["cases"] if c.get("ok")]
    else:
        grader = grader_raw
    if not isinstance(human, list) or not isinstance(grader, list):
        print("human must be a JSON array; grader must be array or mvq-results object", file=sys.stderr)
        return 2

    result = compare_samples(human, grader, line_target=args.line_target, hard_target=args.hard_target)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
