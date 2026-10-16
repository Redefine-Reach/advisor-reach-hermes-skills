#!/usr/bin/env python3
"""Repeat each case N times; all runs must pass (flake guard)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from checks import run_checks  # noqa: E402
from hermes_bridge import HERMES_PIN, prove_wrap, run_fixture, run_hermes  # noqa: E402
from outbound_stub import OutboundRecorder  # noqa: E402
from run_trial import load_cases  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--mode", choices=["fixture", "hermes"], default="fixture")
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--suite", choices=["regression", "capability", "all"], default="all")
    args = parser.parse_args()
    if args.repeats < 5:
        print("repeats must be >= 5", file=sys.stderr)
        return 2

    cases = load_cases(args.limit)
    if args.suite != "all":
        cases = [c for c in cases if c.get("suite") == args.suite]

    proof = prove_wrap()
    report_cases = []
    all_ok = True
    for case in cases:
        runs = []
        case_ok = True
        for n in range(args.repeats):
            rec = OutboundRecorder()
            if args.mode == "hermes":
                run = run_hermes(case, dry_run=args.dry_run, recorder=rec)
            else:
                run = run_fixture(case, recorder=rec)
            ok, failures = run_checks(case, run)
            runs.append({"run": n + 1, "pass": ok, "failures": failures})
            if not ok:
                case_ok = False
                all_ok = False
        report_cases.append(
            {
                "id": case["id"],
                "suite": case.get("suite"),
                "category": case["category"],
                "pass": case_ok,
                "repeats": args.repeats,
                "runs": runs,
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "box": "e23fjkv6",
        "hermes_pin": HERMES_PIN,
        "hermes_wrap_proof": prove_wrap().__dict__,
        "mode": args.mode,
        "dry_run": args.dry_run,
        "repeats": args.repeats,
        "suite_filter": args.suite,
        "summary": {
            "cases": len(report_cases),
            "passed": sum(1 for c in report_cases if c["pass"]),
            "failed": sum(1 for c in report_cases if not c["pass"]),
        },
        "cases": report_cases,
    }
    out = ROOT / "evidence" / "repeat-results.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": all_ok, "evidence": str(out), "summary": payload["summary"]}))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
