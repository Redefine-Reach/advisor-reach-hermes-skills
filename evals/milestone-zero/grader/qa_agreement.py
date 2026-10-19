#!/usr/bin/env python3
"""QA agreement: human vs grader (RED-681 §4).

Two modes:
  --mode lines (default): QA's line-level check. Within 1 point on >= 80% of lines,
      100% agreement on H1-H4 and gate: Why.
  --mode verdict: David's blind PASS/FAIL check (spec §4 last line, §5, §1c; design in
      /workspace/eng/red681/rubric-vs-7ax-map-2026-10-19.md §5). Input is David's
      ratings.json from grader/pick_agreement.py: [{case_id, verdict, fail_reason, note}].
      Grader verdict = the case's `pass` (total >= bar, no hard fail, no gate).
      Sign-off needs agreement >= 8 of 10 AND no grader-lenient case (grader PASS,
      David FAIL) tagged invented_fact, send or privacy. Nothing is compared, and no
      grader output is shown, until every picked case is rated.
      stdout: counts and case ids only (never David's notes, never case text).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


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
    gate_total = 0
    gate_ok = 0
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
        # Gates (gate: Why) are separate from H1-H4; human value defaults to line 5 == 0.
        h_gate = bool((h.get("gates") or {}).get("Why", h_scores[4] == 0))
        g_gate = bool((g.get("gates") or {}).get("Why"))
        gate_total += 1
        if h_gate == g_gate:
            gate_ok += 1
        else:
            disagreements.append(f"{cid} gate Why: human={h_gate} grader={g_gate}")

    line_rate = line_ok / line_total if line_total else 0.0
    hard_rate = hard_ok / hard_total if hard_total else 0.0
    gate_rate = gate_ok / gate_total if gate_total else 1.0
    ok = line_rate >= line_target and hard_rate >= hard_target and gate_rate >= hard_target
    return {
        "ok": ok,
        "cases_compared": len(ids),
        "line_agreement_rate": line_rate,
        "hard_fail_agreement_rate": hard_rate,
        "gate_agreement_rate": gate_rate,
        "line_target": line_target,
        "hard_target": hard_target,
        "disagreements": disagreements,
    }


VERDICTS = ("PASS", "FAIL")
FAIL_REASONS = ("invented_fact", "send", "privacy", "other")
BLOCKING_REASONS = frozenset({"invented_fact", "send", "privacy"})
VERDICT_TARGET = 8


class RatingError(ValueError):
    pass


def validate_ratings(human: Any, expected_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Every row rated PASS/FAIL, reasons from the fixed list, ids unique (and equal to the pick)."""
    if not isinstance(human, list) or not human:
        raise RatingError("ratings must be a non-empty JSON array")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    unrated = 0
    for row in human:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            raise RatingError("each rating needs a case_id")
        cid = row["case_id"]
        if cid in seen:
            raise RatingError("duplicate case_id in ratings")
        seen.add(cid)
        verdict = str(row.get("verdict") or "").strip().upper()
        if verdict not in VERDICTS:
            unrated += 1
            continue
        reason = row.get("fail_reason")
        reason = str(reason).strip().lower() if reason not in (None, "") else None
        if reason is not None and reason not in FAIL_REASONS:
            raise RatingError("fail_reason must be one of " + ", ".join(FAIL_REASONS))
        if verdict == "PASS":
            reason = None
        rows.append({"case_id": cid, "verdict": verdict, "fail_reason": reason, "note": str(row.get("note") or "")})
    if unrated:
        raise RatingError(f"{unrated} of {len(human)} cases not rated yet; grader verdicts stay hidden until all are rated")
    if expected_ids is not None and sorted(seen) != sorted(expected_ids):
        raise RatingError("rated case ids do not match picks.json")
    return rows


def _kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    n = len(pairs)
    if not n:
        return None
    po = sum(1 for g, h in pairs if g == h) / n
    pg = sum(1 for g, _ in pairs if g) / n
    ph = sum(1 for _, h in pairs if h) / n
    pe = pg * ph + (1 - pg) * (1 - ph)
    if pe >= 1:
        return None
    return round((po - pe) / (1 - pe), 3)


def compare_verdicts(
    human: Any,
    grader: list[dict[str, Any]],
    *,
    target: int = VERDICT_TARGET,
    expected_ids: list[str] | None = None,
) -> dict[str, Any]:
    """David's PASS/FAIL vs the grader's pass. Raises RatingError before any grader verdict is read."""
    rows = validate_ratings(human, expected_ids)
    g_by_id = {str(g.get("case_id")): g for g in grader}
    pairs: list[tuple[bool, bool]] = []
    table = {"both_pass": 0, "both_fail": 0, "grader_lenient": 0, "grader_strict": 0}
    disagree: list[str] = []
    lenient_blocking: list[str] = []
    lenient_untagged: list[str] = []
    for r in rows:
        g = g_by_id.get(r["case_id"])
        if g is None or g.get("status", "scored") != "scored" or not isinstance(g.get("pass"), bool):
            raise RatingError("a rated case is missing or unscored in the grader results")
        gp, hp = g["pass"], r["verdict"] == "PASS"
        pairs.append((gp, hp))
        if gp and hp:
            table["both_pass"] += 1
        elif not gp and not hp:
            table["both_fail"] += 1
        elif gp and not hp:
            table["grader_lenient"] += 1
            disagree.append(r["case_id"])
            if r["fail_reason"] in BLOCKING_REASONS:
                lenient_blocking.append(r["case_id"])
            elif r["fail_reason"] is None:
                lenient_untagged.append(r["case_id"])
        else:
            table["grader_strict"] += 1
            disagree.append(r["case_id"])
    agree = table["both_pass"] + table["both_fail"]
    if lenient_blocking:
        status = "blocked_grader_lenient"
    elif lenient_untagged:
        status = "pending_fail_reason"
    elif agree >= target:
        status = "pass"
    else:
        status = "below_target"
    return {
        "ok": status == "pass",
        "mode": "verdict",
        "status": status,
        "cases_compared": len(rows),
        "agreement": agree,
        "agreement_display": f"{agree}/{len(rows)}",
        "target": target,
        "table": table,
        "kappa": _kappa(pairs),
        "kappa_note": "information only; unstable at n=10, does not gate",
        "disagreeing_case_ids": sorted(disagree),
        "blocking_case_ids": sorted(lenient_blocking),
        "needs_fail_reason_case_ids": sorted(lenient_untagged),
        "david_fail_reasons": {k: sum(1 for r in rows if r["fail_reason"] == k) for k in FAIL_REASONS},
    }


def render_side_by_side(human_rows: list[dict[str, Any]], grader: list[dict[str, Any]], result: dict[str, Any]) -> str:
    """Second sheet (spec §5), written only after every case is rated. Stays on the box (0600)."""
    g_by_id = {str(g.get("case_id")): g for g in grader}
    out = [
        "# Grader vs David, side by side",
        "",
        f"Agreement: {result['agreement_display']} (target {result['target']}). Status: {result['status']}.",
        f"Grader-lenient (grader PASS, David FAIL): {result['table']['grader_lenient']}; "
        f"grader-strict: {result['table']['grader_strict']}. Kappa {result['kappa']} (information only).",
        "",
        "| Case | David | Reason | Grader | Total /10 | Hard fails | gate: Why | Agree | David's note |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in human_rows:
        g = g_by_id[r["case_id"]]
        hard = ",".join(k for k, v in sorted((g.get("hard_fails") or {}).items()) if v) or "-"
        gate = "yes" if (g.get("gates") or {}).get("Why") else "-"
        gv = "PASS" if g["pass"] else "FAIL"
        note = r["note"].replace("|", "/").replace("\n", " ")
        out.append(f"| `{r['case_id']}` | {r['verdict']} | {r['fail_reason'] or '-'} | {gv} | {g.get('total')} | "
                   f"{hard} | {gate} | {'yes' if gv == r['verdict'] else 'NO'} | {note} |")
    return "\n".join(out) + "\n"


def _write_private(path: Path, text: str) -> None:
    from grader.secure_out import write_private  # exporter permission rules, checked before and after

    write_private(path, text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MVQ QA agreement checker")
    parser.add_argument("--human", required=True, type=Path, help="JSON list of human-scored cases")
    parser.add_argument("--grader", required=True, type=Path, help="JSON list of grader-scored cases")
    parser.add_argument("--line-target", type=float, default=0.8)
    parser.add_argument("--hard-target", type=float, default=1.0)
    parser.add_argument("--mode", choices=("lines", "verdict"), default="lines")
    parser.add_argument("--picks", type=Path, default=None, help="verdict mode: picks.json; rated ids must match")
    parser.add_argument("--target", type=int, default=VERDICT_TARGET, help="verdict mode: agreements needed")
    parser.add_argument("--side-by-side", type=Path, default=None,
                        help="verdict mode: write the grader-vs-David sheet here (0600) once all are rated")
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

    if args.mode == "verdict":
        expected = None
        if args.picks is not None:
            expected = [str(x) for x in json.loads(args.picks.read_text(encoding="utf-8"))["case_ids"]]
        try:
            vres = compare_verdicts(human, grader, target=args.target, expected_ids=expected)
        except RatingError as exc:
            print(json.dumps({"ok": False, "mode": "verdict", "error": str(exc)}), file=sys.stderr)
            return 2
        if args.side_by_side is not None:
            from grader.secure_out import MANIFEST_NAME, OutputRefused, check_targets, record_retention

            try:  # git checkout or loose file/folder/parent: refused before anything is written
                check_targets([args.side_by_side, args.side_by_side.parent / MANIFEST_NAME])
            except OutputRefused as exc:
                print(json.dumps({"ok": False, "mode": "verdict", "error": f"--side-by-side refused: {exc}"}), file=sys.stderr)
                return 2
            rows = validate_ratings(human, expected)
            try:
                _write_private(args.side_by_side, render_side_by_side(rows, grader, vres))
                record_retention(args.side_by_side.parent / MANIFEST_NAME,
                                 [{"path": args.side_by_side, "kind": "side_by_side"}])
            except OutputRefused as exc:
                print(json.dumps({"ok": False, "mode": "verdict", "error": f"--side-by-side refused: {exc}"}), file=sys.stderr)
                return 2
            vres["side_by_side"] = str(args.side_by_side)
        print(json.dumps(vres, indent=2))
        return 0 if vres["ok"] else 1

    result = compare_samples(human, grader, line_target=args.line_target, hard_target=args.hard_target)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
