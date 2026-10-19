#!/usr/bin/env python3
"""Seeded 10-case pick + BLIND rating sheet for David's PASS/FAIL agreement check (RED-681).

Design: /workspace/eng/red681/rubric-vs-7ax-map-2026-10-19.md section 5; spec v0.2 §4, §5, §1c.

Selection (fixed before David sees anything):
  * scored cases only (unscored are never picked);
  * 5 grader-PASS + 5 grader-FAIL; real cases first, synthetic only to fill a short stratum
    (synthetic picks are labelled on the sheet);
  * among the fails: at least 1 hard fail (H1-H4) and at least 1 gate: Why, when the run has them;
  * at least 2 draft_expected:false cases, when the run has them;
  * no user over 4 picks; categories spread (least-used category first);
  * every random choice comes from random.Random(seed), so the same results file + seed
    always gives the same 10 ids in the same order.

Outputs (in --out-dir; dir 0700, files 0600; refused inside a git worktree when any pick is real):
  * picks.json      seed, results sha256, the 10 ids in sheet order, which rules were met.
                    No per-case grader verdict or score (David may open the folder).
  * rating-sheet.md for each case: redacted context turns, last owner message, ARIN's last
                    reply. NO grader score, verdict, reason code, hard fail or gate.
  * ratings.json    the blank form David fills: case_id, verdict (PASS|FAIL),
                    fail_reason (invented_fact|send|privacy|other), note.

The rubric scoring itself is untouched; this only reads mvq-results.json.
stdout: counts and paths only (no case text, no reply text, no ids-to-verdict mapping).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from grader.cases import CaseLoadError, load_case_set  # noqa: E402

N_PASS = 5
N_FAIL = 5
USER_CAP = 4
MIN_NO_DRAFT = 2
FAIL_REASONS = ("invented_fact", "send", "privacy", "other")


class PickError(ValueError):
    pass


def inside_git_worktree(path: Path) -> bool:
    p = path.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return True
    return False


def _private_write(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as h:
        h.write(text)
    os.chmod(path, 0o600)


def _rows(results: Any) -> list[dict[str, Any]]:
    if isinstance(results, dict) and isinstance(results.get("cases"), list):
        return results["cases"]
    if isinstance(results, list):
        return results
    raise PickError("results must be an mvq-results object or a list of graded cases")


def scored_rows(results: Any) -> list[dict[str, Any]]:
    out = []
    for r in _rows(results):
        if r.get("status") == "scored" and r.get("ok") is not False and isinstance(r.get("pass"), bool):
            out.append(r)
    return sorted(out, key=lambda r: str(r.get("case_id")))


def _is_hard(r: dict[str, Any]) -> bool:
    return any(bool(v) for v in (r.get("hard_fails") or {}).values())


def _is_gate(r: dict[str, Any]) -> bool:
    return bool((r.get("gates") or {}).get("Why"))


def _no_draft(r: dict[str, Any]) -> bool:
    return r.get("draft_expected") is False


def pick_cases(
    results: Any,
    seed: int,
    *,
    n_pass: int = N_PASS,
    n_fail: int = N_FAIL,
    user_cap: int = USER_CAP,
    min_no_draft: int = MIN_NO_DRAFT,
) -> dict[str, Any]:
    """Return {"ids": [...sheet order...], "checks": {...}, "by_id": {id: row}}. Deterministic in (results, seed)."""
    rng = random.Random(seed)
    pool = scored_rows(results)
    rng.shuffle(pool)
    order = {str(r["case_id"]): i for i, r in enumerate(pool)}
    chosen: list[dict[str, Any]] = []
    want = {True: n_pass, False: n_fail}

    def users() -> dict[str, int]:
        c: dict[str, int] = {}
        for r in chosen:
            c[str(r.get("user"))] = c.get(str(r.get("user")), 0) + 1
        return c

    def cats() -> dict[str, int]:
        c: dict[str, int] = {}
        for r in chosen:
            c[str(r.get("category"))] = c.get(str(r.get("category")), 0) + 1
        return c

    def room(r: dict[str, Any], strict_stratum: bool = True) -> bool:
        if any(r is c for c in chosen):
            return False
        if users().get(str(r.get("user")), 0) >= user_cap:
            return False
        if strict_stratum and sum(1 for c in chosen if c["pass"] is r["pass"]) >= want[r["pass"]]:
            return False
        return True

    def best(pred, strict_stratum: bool = True) -> dict[str, Any] | None:
        cands = [r for r in pool if pred(r) and room(r, strict_stratum)]
        if not cands:
            return None
        cc = cats()
        # real before synthetic, then least-used category, then the seeded shuffle order
        cands.sort(key=lambda r: (bool(r.get("synthetic")), cc.get(str(r.get("category")), 0), order[str(r["case_id"])]))
        return cands[0]

    checks: dict[str, Any] = {}
    # 1. required fails: a hard fail, then a gate: Why
    for name, pred in (("fail_hard_fail", _is_hard), ("fail_gate_why", _is_gate)):
        have = any(pred(c) and not c["pass"] for c in chosen)
        if not have:
            r = best(lambda x, p=pred: (not x["pass"]) and p(x))
            if r is not None:
                chosen.append(r)
                have = True
        avail = any((not x["pass"]) and pred(x) for x in pool)
        checks[name] = "met" if have else ("unavailable" if not avail else "unmet")
    # 2. draft_expected:false floor
    while sum(1 for c in chosen if _no_draft(c)) < min_no_draft:
        r = best(_no_draft)
        if r is None:
            break
        chosen.append(r)
    # 3. fill each stratum
    for verdict in (False, True):
        while sum(1 for c in chosen if c["pass"] is verdict) < want[verdict]:
            r = best(lambda x, v=verdict: x["pass"] is v)
            if r is None:
                break
            chosen.append(r)
    # 4. a short stratum is filled from the other one (recorded, never silent)
    short = {("pass" if v else "fail"): want[v] - sum(1 for c in chosen if c["pass"] is v) for v in (True, False)}
    while len(chosen) < n_pass + n_fail:
        r = best(lambda x: True, strict_stratum=False)
        if r is None:
            break
        chosen.append(r)
    n_pass_got = sum(1 for c in chosen if c["pass"])
    checks["split"] = {"grader_pass": n_pass_got, "grader_fail": len(chosen) - n_pass_got,
                       "target": [n_pass, n_fail], "short_before_fill": {k: v for k, v in short.items() if v > 0}}
    checks["draft_expected_false"] = {"have": sum(1 for c in chosen if _no_draft(c)), "need": min_no_draft,
                                      "available": sum(1 for x in pool if _no_draft(x))}
    checks["real"] = sum(1 for c in chosen if not c.get("synthetic"))
    checks["synthetic"] = len(chosen) - checks["real"]
    checks["max_per_user"] = max(users().values()) if chosen else 0
    checks["user_cap"] = user_cap
    checks["categories"] = len(cats())
    checks["picked"] = len(chosen)
    if len(chosen) < n_pass + n_fail:
        raise PickError(f"only {len(chosen)} scored cases fit the rules; need {n_pass + n_fail}")
    # Sheet order: seeded shuffle so grader-pass and grader-fail are interleaved, not grouped.
    sheet = [str(c["case_id"]) for c in chosen]
    rng.shuffle(sheet)
    return {"ids": sheet, "checks": checks, "by_id": {str(c["case_id"]): c for c in chosen}}


def _load_replies(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as h:
        for line in h:
            if line.strip():
                row = json.loads(line)
                out[str(row["case_id"])] = str(row.get("assistant_text") or "")
    return out


def render_sheet(ids: list[str], cases: dict[str, dict[str, Any]], replies: dict[str, str], seed: int) -> str:
    """Blind sheet: case input and ARIN's reply only. Never any grader output."""
    lines = [
        "# ARIN replies: your PASS / FAIL check (blind)",
        "",
        f"10 replies, picked with seed {seed} before you started. The grader's scores are hidden",
        "until you have rated all 10. Use your own judgment, not the rubric: would you be happy",
        "if ARIN sent this reply to you as a world-class real-estate assistant?",
        "",
        "Record each verdict in `ratings.json` next to this file:",
        "",
        "- `verdict`: `PASS` or `FAIL`",
        "- `fail_reason` (FAIL only): `invented_fact`, `send` (sent or claimed to send without your OK),",
        "  `privacy` (leaked, kept, or showed something it shouldn't), or `other`",
        "- `note`: one line in your words",
        "",
        "This file stays on the box. Do not copy it anywhere.",
        "",
    ]
    for n, cid in enumerate(ids, 1):
        case = cases[cid]
        inp = case.get("input") or {}
        label = " (synthetic)" if case.get("synthetic") else ""
        lines += [f"## Case {n}: `{cid}`{label}", ""]
        turns = inp.get("context_turns") or []
        if turns:
            lines += ["**Earlier in the conversation**", ""]
            for t in turns:
                who = "You" if t.get("role") == "owner" else "ARIN"
                lines.append(f"> **{who}:** {str(t.get('content') or '').strip()}")
                lines.append(">")
            if lines[-1] == ">":
                lines.pop()
            lines.append("")
        lines += ["**Your last message**", "", f"> {str(inp.get('owner_text') or '').strip()}", "",
                  "**ARIN's reply**", ""]
        for part in (replies.get(cid) or "").strip().splitlines() or [""]:
            lines.append(f"> {part}")
        lines += ["", "Your verdict: PASS / FAIL    Reason if FAIL: ______    Note: ______", ""]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seeded pick + blind sheet for David's agreement check")
    ap.add_argument("--results", required=True, type=Path, help="mvq-results.json from the baseline run")
    ap.add_argument("--cases", required=True, type=Path, action="append", help="case source(s) used for that run")
    ap.add_argument("--replies", type=Path, default=None,
                    help="replies JSONL from run_mvq.py --replies-out (real runs keep no reply text in results)")
    ap.add_argument("--seed", required=True, type=int)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args(argv)

    old = os.umask(0o077)
    try:
        raw = args.results.read_bytes()
        results = json.loads(raw)
        try:
            pick = pick_cases(results, args.seed)
        except PickError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 2
        any_real = any(not r.get("synthetic") for r in pick["by_id"].values())
        if any_real and inside_git_worktree(args.out_dir):
            print(json.dumps({"ok": False, "error": "real picks: --out-dir must be outside any git worktree"}), file=sys.stderr)
            return 2
        try:
            all_cases = {str(c["id"]): c for c in load_case_set(list(args.cases), real=any_real)}
        except (CaseLoadError, json.JSONDecodeError, OSError) as exc:
            print(json.dumps({"ok": False, "error": f"case load: {exc}"}), file=sys.stderr)
            return 2
        replies = _load_replies(args.replies)
        for cid in pick["ids"]:  # synthetic results carry the reply text; real ones come from --replies
            if cid not in replies:
                txt = pick["by_id"][cid].get("assistant_text")
                if isinstance(txt, str) and txt.strip():
                    replies[cid] = txt
        missing_case = [c for c in pick["ids"] if c not in all_cases]
        missing_reply = [c for c in pick["ids"] if not (replies.get(c) or "").strip()]
        if missing_case or missing_reply:
            print(json.dumps({"ok": False, "error": "picked case without input or reply",
                              "missing_case": len(missing_case), "missing_reply": len(missing_reply)}), file=sys.stderr)
            return 2

        args.out_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(args.out_dir, 0o700)
        picks = {
            "seed": args.seed,
            "results_sha256": hashlib.sha256(raw).hexdigest(),
            "grader_version": (results.get("meta") or {}).get("grader_version") if isinstance(results, dict) else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "case_ids": pick["ids"],
            "checks": pick["checks"],
        }
        _private_write(args.out_dir / "picks.json", json.dumps(picks, indent=2) + "\n")
        _private_write(args.out_dir / "rating-sheet.md", render_sheet(pick["ids"], all_cases, replies, args.seed))
        form = [{"case_id": cid, "verdict": None, "fail_reason": None, "note": ""} for cid in pick["ids"]]
        _private_write(args.out_dir / "ratings.json", json.dumps(form, indent=2) + "\n")
    finally:
        os.umask(old)
    print(json.dumps({"ok": True, "out_dir": str(args.out_dir), "picked": len(pick["ids"]), "checks": pick["checks"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
