#!/usr/bin/env python3
"""Run milestone-zero trial and write evidence/trial-results.json."""

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
from redact import redact  # noqa: E402

try:
    from task import load_cases
except ImportError:
    def load_cases(limit=None):
        rows = []
        with (ROOT / "cases.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
                if limit and len(rows) >= limit:
                    break
        return rows


def run_inspect(limit: int) -> dict | None:
    try:
        from inspect_ai import eval as inspect_eval
        from task import arin_milestone_zero
    except ImportError:
        return None
    logs = inspect_eval(arin_milestone_zero(limit=limit), log_dir=str(ROOT / "evidence"))
    paths = [str(log.location) for log in logs]
    return {"inspect": True, "log_paths": paths, "log_count": len(paths)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--mode", choices=["fixture", "hermes"], default="fixture")
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--prove-wrap", action="store_true", default=True)
    parser.add_argument("--skip-inspect", action="store_true", help="Only write JSON evidence")
    args = parser.parse_args()

    proof = prove_wrap()
    cases = load_cases(args.limit)
    per_case = []
    passed = 0
    for case in cases:
        owner = case["input"]["owner_text"]
        redacted, codes = redact(owner)
        if args.mode == "hermes":
            run = run_hermes(case, dry_run=args.dry_run)
        else:
            run = run_fixture(case)
        ok, failures = run_checks(case, run)
        if ok:
            passed += 1
        per_case.append(
            {
                "id": case["id"],
                "category": case["category"],
                "pass": ok,
                "failures": failures,
                "redaction_codes": codes,
                "redacted_input": redacted,
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "box": "e23fjkv6",
        "hermes_pin": HERMES_PIN,
        "hermes_wrap_proof": proof.__dict__,
        "mode": args.mode,
        "dry_run": args.dry_run,
        "summary": {"total": len(per_case), "passed": passed, "failed": len(per_case) - passed},
        "cases": per_case,
    }
    if not args.skip_inspect:
        inspect_block = run_inspect(args.limit)
        if inspect_block:
            payload["inspect_eval"] = inspect_block

    evidence_dir = ROOT / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out = evidence_dir / "trial-results.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "evidence": str(out), "summary": payload["summary"]}))
    if args.prove_wrap and not proof.ok:
        print("blocker: hermes 0.21.0 wrap not verified on this host", file=sys.stderr)
    return 0 if passed == len(per_case) else 1


if __name__ == "__main__":
    raise SystemExit(main())
