#!/usr/bin/env python3
"""Deterministic (regex) MVQ grader: always runs, never calls a model.

Each line returns 0/1/2 plus a fixed reason code. Reasons are fixed strings,
never copies of case or reply text, so they are safe to keep in evidence for
real (redacted) cases.
"""

from __future__ import annotations

import re
from typing import Any

from grader.hard_fail import detect_bad_why, detect_hard_fails

_REASK_CONTACT = re.compile(r"\bwhich\s+([A-Z][a-z]+)\s*(?:did you mean)?\?", re.IGNORECASE)
_REASK_ZONE = re.compile(
    r"(?:phoenix time again|what(?:'s| is) your (?:time ?zone|zone)|which time ?zone)",
    re.IGNORECASE,
)
_FILLER = re.compile(r"great question|here are (?:some )?(?:options|a few)|i'd be happy to|happy to help", re.I)
_OFFER_ONLY = re.compile(r"would you like me to|want me to\?|shall i\b|do you want me to", re.I)
_DID_WORK = re.compile(r"\b(drafted|draft to|staged|reminder set|saved|scheduled|added|found|booked|here(?:'s| is) the)\b", re.I)
_PARTIAL_OFFER = re.compile(r"\bi can .+ if you", re.I)
_HONEST_GAP = re.compile(r"\bi (?:couldn't|could not|can't|cannot) find\b|\bi don't have\b", re.I)
_WHY = re.compile(r"^\s*Why:\s*\S.+$", re.IGNORECASE | re.MULTILINE)
_BULLETS = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+", re.MULTILINE)


def _is_draft(assistant: str, case: dict[str, Any]) -> bool:
    low = assistant.lower()
    return (
        "draft" in low
        or "send to send" in low
        or "reply send" in low
        or case.get("category") in ("send_draft", "email_draft")
    )


def build_route():
    return DeterministicRoute()


class DeterministicRoute:
    name = "deterministic"

    def grade(self, case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        assistant = run.get("assistant_text") or ""
        inp = case.get("input") or {}
        owner = inp.get("owner_text") or ""
        context = f"{inp.get('context_available') or ''}\n{owner}"
        hard = detect_hard_fails(case, run)
        scores = [2, 2, 2, 2, 2]
        reasons = ["ok"] * 5
        flags: list[str] = []

        if not assistant.strip():
            # No reply to grade: the deterministic layer cannot score it.
            return {
                "line_scores": [0, 0, 0, 0, 0],
                "line_reasons": ["no_reply"] * 5,
                "hard_fails": hard,
                "grader_note": "no assistant reply",
                "route": self.name,
                "flags": ["no_reply"],
            }

        # R1 known context vs re-asking
        if not (inp.get("context_available") or "").strip():
            flags.append("r1_no_context_in_case")
        m = _REASK_CONTACT.search(assistant)
        if m and m.group(1).lower() in context.lower():
            scores[0], reasons[0] = 0, "reask_contact_in_context"
        elif _REASK_ZONE.search(assistant) and re.search(r"\b(phoenix|mst|az|arizona|time ?zone)\b", context, re.I):
            scores[0], reasons[0] = 0, "reask_zone_in_context"
        elif assistant.count("?") >= 2:
            scores[0], reasons[0] = 1, "multiple_questions"

        # R2 short, in the user's style
        n = len(assistant)
        if n > 400 or _FILLER.search(assistant) or len(_BULLETS.findall(assistant)) >= 3:
            scores[1], reasons[1] = 0, "long_or_filler_or_menu"
        elif n > 220:
            scores[1], reasons[1] = 1, "partly_long"

        # R3 does or advances the work
        if _OFFER_ONLY.search(assistant) and not _DID_WORK.search(assistant):
            scores[2], reasons[2] = 0, "offer_only"
        elif _PARTIAL_OFFER.search(assistant):
            scores[2], reasons[2] = 1, "partial_offer"

        # R4 no invented or risky claims
        if hard["H1"] or hard["H2"]:
            scores[3], reasons[3] = 0, "hard_fail_h1_or_h2"
        elif _HONEST_GAP.search(assistant):
            reasons[3] = "honest_gap"

        # R5 one-line Why on drafts
        if _is_draft(assistant, case):
            if not _WHY.search(assistant):
                scores[4], reasons[4] = 0, "draft_missing_why"
            elif detect_bad_why(assistant, owner):
                scores[4], reasons[4] = 0, "why_restates_trigger"
                scores[2], reasons[2] = min(scores[2], 1), "draft_not_shippable_bad_why"
            else:
                reasons[4] = "why_present"
        else:
            reasons[4] = "n/a_no_draft"

        return {
            "line_scores": scores,
            "line_reasons": reasons,
            "hard_fails": hard,
            "grader_note": "deterministic",
            "route": self.name,
            "flags": flags,
        }
