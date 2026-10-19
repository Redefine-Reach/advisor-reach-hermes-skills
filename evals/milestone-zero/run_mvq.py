#!/usr/bin/env python3
"""Run the MVQ grader (RED-681).

Synthetic mode (default, CI): cases_mvq_synthetic.jsonl, fixture replies,
evidence written to --evidence-dir (default ./evidence).

Real mode (--real, ARIN TEST only): cases are redacted internal-user cases that
live on the box (e.g. /opt/data/eval-export/<run>/redacted/cases-export.jsonl).
  * --evidence-dir is required and must be outside any git worktree;
    dirs are created 0700, files 0600.
  * Results keep scores, fixed reason codes and hard-fail flags only: no case
    text, no reply text, no judge reasons.
  * stdout prints counts only.
  * Judge routes other than deterministic are refused unless
    ARIN_MVQ_REAL_JUDGE_ALLOWED names that exact route (needs Vault + David).

Order (harness2 lesson): the case set and reply are SELECTED first (case list
hashed and frozen, behavior checks run), then EVERY selected case is scored.
A failed judge marks the case "unscored", never "fail".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from checks import run_checks  # noqa: E402
from grader.cases import CaseLoadError, load_case_set, real_set_report, selection_sha256  # noqa: E402
from grader.config import load_grader_config  # noqa: E402
from grader.model_route import ENV_ROUTE  # noqa: E402
from grader.qa_agreement import compare_samples  # noqa: E402
from grader.scorecard import render_scorecard  # noqa: E402
from grader.scorer import REAL_SAFE_JUDGES, grade_case, grade_run_outbound_guard  # noqa: E402
from grader.version import GRADER_VERSION  # noqa: E402
from hermes_bridge import ensure_live_session, run_fixture, run_hermes, shutdown_live_session  # noqa: E402
from outbound_stub import OutboundRecorder  # noqa: E402

ENV_REAL_JUDGE_ALLOWED = "ARIN_MVQ_REAL_JUDGE_ALLOWED"


def inside_git_worktree(path: Path) -> bool:
    p = path.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return True
    return False


def secure_write(path: Path, text: str, private: bool) -> None:
    if private:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            h.write(text)
        os.chmod(path, 0o600)
    else:
        path.write_text(text, encoding="utf-8")


def score_counts(rows: list[dict]) -> dict:
    lines = {f"R{i + 1}": Counter() for i in range(5)}
    hard = Counter()
    status = Counter()
    for r in rows:
        status[r.get("status", "unscored")] += 1
        if r.get("status") == "scored":
            for i, s in enumerate(r["line_scores"]):
                lines[f"R{i + 1}"]["n/a" if s is None else str(s)] += 1
            status["pass" if r.get("pass") else "fail"] += 1
            for k, v in (r.get("hard_fails") or {}).items():
                if v:
                    hard[k] += 1
        else:
            for k in lines:
                lines[k]["unscored"] += 1
    return {
        "lines": {k: {s: v.get(s, 0) for s in ("0", "1", "2", "n/a", "unscored")} for k, v in lines.items()},
        "hard_fails": {k: hard.get(k, 0) for k in ("H1", "H2", "H3", "H4")},
        "status": dict(status),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--cases",
        type=Path,
        action="append",
        default=None,
        help="JSONL file or syn-NNN.json directory; repeatable. Default: ours + Jerry's synthetic set",
    )
    ap.add_argument("--real", action="store_true", help="redacted exported cases on ARIN TEST")
    ap.add_argument("--live", action="store_true", help="get replies from stub-only live Hermes (ARIN TEST)")
    ap.add_argument("--evidence-dir", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--build-image", default=os.environ.get("ARIN_MVQ_BUILD_IMAGE", "synthetic-fixture"))
    ap.add_argument("--qa-human", type=Path, default=None)
    ap.add_argument("--skip-behavior-checks", action="store_true")
    args = ap.parse_args()

    judge = (os.environ.get(ENV_ROUTE) or "").strip()
    if args.real:
        if args.evidence_dir is None:
            print(json.dumps({"ok": False, "error": "--real needs --evidence-dir outside git"}), file=sys.stderr)
            return 2
        if inside_git_worktree(args.evidence_dir):
            print(json.dumps({"ok": False, "error": "real cases/evidence must be outside any git worktree"}), file=sys.stderr)
            return 2
        if judge.lower() not in REAL_SAFE_JUDGES and os.environ.get(ENV_REAL_JUDGE_ALLOWED, "") != judge:
            print(json.dumps({"ok": False, "error": f"judge route '{judge}' not approved for real cases"}), file=sys.stderr)
            return 2
    evidence_dir = args.evidence_dir or (ROOT / "evidence")
    old_umask = os.umask(0o077) if args.real else None
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if args.real:
        os.chmod(evidence_dir, 0o700)

    config = load_grader_config()
    sources = args.cases or [ROOT / "cases_mvq_synthetic.jsonl", ROOT / "cases_mvq_jerry"]
    try:
        cases = load_case_set(sources, real=args.real)
        if args.real:
            for src in sources:  # real (non-synthetic) cases must not come from a git checkout
                if inside_git_worktree(src) and any(not c.get("synthetic") for c in load_case_set([src], real=True)):
                    raise CaseLoadError("real cases must live outside any git worktree")
    except (CaseLoadError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": f"case load: {exc}"}), file=sys.stderr)
        return 2
    if args.limit:
        cases = cases[: args.limit]
    # Selection is frozen (and hashed) before any reply is produced or scored.
    selection = [str(c.get("id")) for c in cases]
    selection_sha = selection_sha256(cases)
    set_report = real_set_report(cases)

    live_ctx = None
    if args.live:
        live_ctx, err = ensure_live_session()
        if err:
            print(json.dumps({"ok": False, "error": f"live session: {err}"}), file=sys.stderr)
            return 2

    runs: list[dict] = []
    try:
        for case in cases:
            rec = OutboundRecorder()
            if args.live:
                run = run_hermes(case, dry_run=False, recorder=rec, live_ctx=live_ctx)
            else:
                run = run_fixture(case, recorder=rec)
                run["outbound_log"] = rec.snapshot()
            run["case_id"] = case["id"]
            if not args.skip_behavior_checks:
                ok, failures = run_checks(case, run)
                run["behavior_ok"] = ok
                run["behavior_failures"] = len(failures)
            runs.append(run)
    finally:
        if live_ctx is not None:
            shutdown_live_session()

    guard_ok, guard_err = grade_run_outbound_guard(runs)

    # Score every selected case (behavior failures are recorded, not dropped).
    graded: list[dict] = []
    for case, run in zip(cases, runs):
        g = grade_case(case, run, config=config, include_text=not args.real)
        g["behavior_ok"] = run.get("behavior_ok")
        g["behavior_failures"] = run.get("behavior_failures", 0)
        if run.get("ok") is False:
            g.update({"ok": False, "status": "unscored", "error": "run_failed"})
            g.pop("pass", None)
        graded.append(g)

    counts = score_counts(graded)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_image": args.build_image,
        "grader_version": GRADER_VERSION,
        "bar": config.bar,
        "judge_route": judge or "deterministic",
        "synthetic_only": set_report["real"] == 0,
        "replies": "live_stub" if args.live else "recorded",
        "selection_sha256": selection_sha,
        "cases_selected": len(selection),
        "cases_real": set_report["real"],
        "cases_synthetic": set_report["synthetic"],
        "set_report": set_report,
    }
    scored = [g for g in graded if g.get("status") == "scored"]
    payload = {
        "ok": guard_ok,
        "run_error": guard_err,
        "meta": meta,
        "summary": {
            "total": len(graded),
            "graded": len(scored),
            "unscored": len(graded) - len(scored),
            "behavior_failed": sum(1 for g in graded if g.get("behavior_ok") is False),
            "mvq_passed": sum(1 for g in scored if g.get("pass")),
            "mvq_failed": sum(1 for g in scored if not g.get("pass")),
        },
        "counts": counts,
        "qa": None,
        "cases": graded,
    }
    if args.qa_human and args.qa_human.is_file():
        payload["qa"] = compare_samples(json.loads(args.qa_human.read_text(encoding="utf-8")), scored)

    results_path = evidence_dir / "mvq-results.json"
    secure_write(results_path, json.dumps(payload, indent=2) + "\n", args.real)
    out = {"ok": guard_ok, "evidence": str(results_path), "summary": payload["summary"], "counts": counts,
           "counts_real": score_counts([g for g in graded if not g.get("synthetic")]),
           "selection_sha256": selection_sha, "set_report": set_report}
    if not args.real:  # scorecard carries reply text; synthetic only
        sc = evidence_dir / "mvq-scorecard.md"
        secure_write(sc, render_scorecard(meta, scored, qa_block=payload["qa"], unscored=len(graded) - len(scored)), args.real)
        out["scorecard"] = str(sc)
    if old_umask is not None:
        os.umask(old_umask)
    print(json.dumps(out))
    if not guard_ok:
        return 3
    return 0 if payload["summary"]["behavior_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
