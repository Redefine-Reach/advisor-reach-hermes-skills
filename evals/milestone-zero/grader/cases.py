#!/usr/bin/env python3
"""MVQ case loading, normalization, schema validation and the frozen selection (RED-681 v0.2).

Sources (one frozen, hashed list):
  * JSONL files (ours: cases_mvq_synthetic.jsonl; exported real cases on ARIN TEST)
  * a directory of syn-NNN.json files (Jerry's synthetic set, with INDEX.md)
Case ids must be unique across every source; a duplicate fails the load.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CATEGORIES = frozenset({
    "send_draft", "scheduling", "buyer_profile", "follow_up", "reask_context", "do_not_keep",
    "email_draft", "unlabeled", "no_answer", "memory_save",
    # grader self-test categories (ours)
    "invented_fact", "why_line", "stall", "style_long",
})
TURN_ROLES = frozenset({"owner", "arin"})
REAL_COVERAGE_TARGET = {
    "send_draft": 4, "scheduling": 2, "buyer_profile": 2, "follow_up": 2, "reask_context": 2, "email_draft": 2,
}
STRUGGLED_REAL_TARGET = 8
REAL_PER_USER_CAP = 10


class CaseLoadError(ValueError):
    pass


def _normalize_jerry(case: dict[str, Any]) -> dict[str, Any]:
    """syn-NNN.json (input_turns + context_available dict) -> harness case shape."""
    turns = case.get("input_turns")
    if not isinstance(turns, list):
        return case
    inp = dict(case.get("input") or {})
    norm = [{"role": str(t.get("role") or ""), "content": t.get("text")} for t in turns if isinstance(t, dict)]
    if norm and norm[-1]["role"] == "owner" and norm[-1]["content"] == inp.get("owner_text"):
        norm = norm[:-1]
    inp["context_turns"] = norm
    ctx = case.get("context_available")
    if isinstance(ctx, dict) and isinstance(ctx.get("style_sample"), list):
        inp["style_sample"] = list(ctx["style_sample"])
    out = dict(case)
    out["input"] = inp
    return out


def validate_case(case: dict[str, Any]) -> list[str]:
    """Schema errors (field names only, never values)."""
    errs: list[str] = []
    cid = case.get("id")
    tag = cid if isinstance(cid, str) and cid else "<no id>"
    if not isinstance(cid, str) or not cid.strip():
        errs.append(f"{tag}: id missing")
    if not isinstance(case.get("synthetic"), bool):
        errs.append(f"{tag}: synthetic must be true/false")
    if case.get("category") not in CATEGORIES:
        errs.append(f"{tag}: unknown category")
    de = case.get("draft_expected")
    if de is not None and not isinstance(de, bool):
        errs.append(f"{tag}: draft_expected must be true/false/null")
    if case.get("synthetic") is True and not isinstance(de, bool):
        errs.append(f"{tag}: synthetic cases must set draft_expected")
    if "struggled" in case and not isinstance(case["struggled"], bool):
        errs.append(f"{tag}: struggled must be true/false")
    inp = case.get("input")
    if not isinstance(inp, dict):
        errs.append(f"{tag}: input missing")
        return errs
    if not isinstance(inp.get("owner_text"), str) or not inp["owner_text"].strip():
        errs.append(f"{tag}: input.owner_text missing")
    if not isinstance(inp.get("channel", "sms"), str):
        errs.append(f"{tag}: input.channel must be a string")
    if "context_available" in inp and not isinstance(inp["context_available"], str):
        errs.append(f"{tag}: input.context_available must be a string")
    for i, t in enumerate(inp.get("context_turns") or []):
        if not isinstance(t, dict) or t.get("role") not in TURN_ROLES or not isinstance(t.get("content"), str):
            errs.append(f"{tag}: input.context_turns[{i}] needs role owner|arin and string content")
    ss = inp.get("style_sample")
    if ss is not None and (not isinstance(ss, list) or not all(isinstance(x, str) for x in ss)):
        errs.append(f"{tag}: input.style_sample must be a list of strings")
    if "expect" in case and not isinstance(case["expect"], dict):
        errs.append(f"{tag}: expect must be an object")
    if isinstance(case.get("input_turns"), list):
        last = case["input_turns"][-1] if case["input_turns"] else {}
        if not isinstance(last, dict) or last.get("role") != "owner" or last.get("text") != inp.get("owner_text"):
            errs.append(f"{tag}: last input_turn must be the owner turn equal to input.owner_text")
    return errs


def _read_source(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        rows = []
        for f in sorted(path.glob("*.json")):
            rows.append(json.loads(f.read_text(encoding="utf-8")))
        return rows
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_case_set(paths: list[Path], *, real: bool) -> list[dict[str, Any]]:
    """Load, normalize and validate every source; fail on schema errors or duplicate ids."""
    cases: list[dict[str, Any]] = []
    for p in paths:
        for raw in _read_source(p):
            case = _normalize_jerry(raw)
            case.setdefault("synthetic", False)
            case.setdefault("user", "synthetic" if case.get("synthetic") else "unknown")
            cases.append(case)
    errs: list[str] = []
    seen: dict[str, int] = {}
    for c in cases:
        errs.extend(validate_case(c))
        cid = str(c.get("id"))
        seen[cid] = seen.get(cid, 0) + 1
    dups = sorted(k for k, v in seen.items() if v > 1)
    if dups:
        errs.append(f"duplicate case ids: {', '.join(dups)}")
    if not real:
        if any(not c.get("synthetic") for c in cases):
            errs.append("non-synthetic case outside --real mode")
    if errs:
        raise CaseLoadError("; ".join(errs))
    return cases


def selection_sha256(cases: list[dict[str, Any]]) -> str:
    return hashlib.sha256("\n".join(str(c.get("id")) for c in cases).encode()).hexdigest()


def real_set_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the real-case rules (synthetic never counted)."""
    real = [c for c in cases if not c.get("synthetic")]
    per_user: dict[str, int] = {}
    per_cat: dict[str, int] = {}
    for c in real:
        per_user[str(c.get("user"))] = per_user.get(str(c.get("user")), 0) + 1
        per_cat[str(c.get("category"))] = per_cat.get(str(c.get("category")), 0) + 1
    return {
        "real": len(real),
        "synthetic": len(cases) - len(real),
        "struggled_real": sum(1 for c in real if c.get("struggled") is True),
        "struggled_target": STRUGGLED_REAL_TARGET,
        "per_user_real": per_user,
        "users_over_cap": sorted(u for u, n in per_user.items() if n > REAL_PER_USER_CAP),
        "coverage_real": {k: {"have": per_cat.get(k, 0), "need": v} for k, v in REAL_COVERAGE_TARGET.items()},
    }
