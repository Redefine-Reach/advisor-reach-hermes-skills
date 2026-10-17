#!/usr/bin/env python3
"""Run MVQ grader on synthetic cases; write JSON + markdown scorecard."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from checks import run_checks  # noqa: E402
from grader.config import load_grader_config  # noqa: E402
from grader.model_route import ENV_ROUTE, require_route_name  # noqa: E402
from grader.qa_agreement import compare_samples  # noqa: E402
from grader.scorecard import render_scorecard  # noqa: E402
from grader.scorer import grade_case, grade_run_outbound_guard  # noqa: E402
from grader.version import GRADER_VERSION  # noqa: E402
from hermes_bridge import run_fixture  # noqa: E402
from outbound_stub import OutboundRecorder  # noqa: E402


def load_mvq_cases(path: Path, limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if not case.get("synthetic"):
                raise ValueError(f"case {case.get('id')} is not marked synthetic=true")
            rows.append(case)
            if limit and len(rows) >= limit:
                break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "cases_mvq_synthetic.jsonl",
        help="Synthetic MVQ cases only",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--build-image", default=os.environ.get("ARIN_MVQ_BUILD_IMAGE", "synthetic-fixture"))
    parser.add_argument("--qa-human", type=Path, default=None, help="Optional QA human sample JSON")
    parser.add_argument("--skip-behavior-checks", action="store_true")
    args = parser.parse_args()

    try:
        require_route_name()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "env": ENV_ROUTE}), file=sys.stderr)
        return 2

    config = load_grader_config()
    cases = load_mvq_cases(args.cases, args.limit)
    runs_for_guard: list[dict] = []
    graded: list[dict] = []
    behavior_failed = 0

    for case in cases:
        rec = OutboundRecorder()
        run = run_fixture(case, recorder=rec)
        run["outbound_log"] = rec.snapshot()
        run["case_id"] = case["id"]
        runs_for_guard.append(run)

        if not args.skip_behavior_checks:
            ok, failures = run_checks(case, run)
            if not ok:
                behavior_failed += 1
                graded.append(
                    {
                        "ok": False,
                        "case_id": case["id"],
                        "user": case.get("user"),
                        "category": case.get("category"),
                        "pass": False,
                        "error": "; ".join(failures),
                        "grader_version": GRADER_VERSION,
                        "config": config.to_dict(),
                    }
                )
                continue

        result = grade_case(case, run, config=config)
        graded.append(result)

    guard_ok, guard_err = grade_run_outbound_guard(runs_for_guard)
    if not guard_ok:
        payload = {
            "ok": False,
            "error": guard_err,
            "grader_version": GRADER_VERSION,
            "cases": graded,
        }
        evidence = ROOT / "evidence" / "mvq-results.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "error": guard_err, "evidence": str(evidence)}), file=sys.stderr)
        return 3

    ok_rows = [g for g in graded if g.get("ok")]
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_image": args.build_image,
        "grader_version": GRADER_VERSION,
        "bar": config.bar,
        "route": os.environ.get(ENV_ROUTE),
        "synthetic_only": True,
    }

    qa_block = None
    if args.qa_human and args.qa_human.is_file():
        human = json.loads(args.qa_human.read_text(encoding="utf-8"))
        qa_block = compare_samples(human, ok_rows)

    scorecard_md = render_scorecard(meta, ok_rows, qa_block=qa_block)
    evidence_dir = ROOT / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results_path = evidence_dir / "mvq-results.json"
    scorecard_path = evidence_dir / "mvq-scorecard.md"

    payload = {
        "ok": behavior_failed == 0 and all(r.get("pass") is not None for r in ok_rows),
        "meta": meta,
        "summary": {
            "total": len(graded),
            "graded": len(ok_rows),
            "behavior_failed": behavior_failed,
            "mvq_passed": sum(1 for r in ok_rows if r.get("pass")),
            "mvq_failed": sum(1 for r in ok_rows if not r.get("pass")),
        },
        "qa": qa_block,
        "cases": graded,
    }
    results_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    scorecard_path.write_text(scorecard_md, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": payload["ok"],
                "evidence": str(results_path),
                "scorecard": str(scorecard_path),
                "summary": payload["summary"],
            }
        )
    )
    return 0 if payload["summary"]["behavior_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
