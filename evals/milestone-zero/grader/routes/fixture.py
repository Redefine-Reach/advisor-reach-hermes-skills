#!/usr/bin/env python3
"""Rule-based grader route for synthetic CI fixtures (no external model)."""

from __future__ import annotations

import re
from typing import Any

from grader.hard_fail import detect_bad_why, detect_hard_fails


def build_route():
    return FixtureRoute()


class FixtureRoute:
    """Deterministic rubric approximation for synthetic cases and unit tests."""

    def grade(self, case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        gf = case.get("grader", {}).get("fixture_scores")
        if gf:
            return {
                "line_scores": list(gf["line_scores"]),
                "line_reasons": list(gf.get("line_reasons") or ["fixture"] * 5),
                "hard_fails": dict(gf.get("hard_fails") or detect_hard_fails(case, run)),
                "grader_note": gf.get("grader_note", "fixture_scores"),
                "route": "fixture",
            }

        assistant = run.get("assistant_text") or ""
        owner = (case.get("input") or {}).get("owner_text") or ""
        context = (case.get("input") or {}).get("context_available") or ""
        hard = detect_hard_fails(case, run)

        scores = [2, 2, 2, 2, 2]
        reasons = ["meets rubric (fixture rules)", "meets rubric (fixture rules)"] * 2 + [
            "meets rubric (fixture rules)"
        ]

        if re.search(r"which (dana|chris|ryan)\?", assistant, re.IGNORECASE):
            scores[0] = 0
            reasons[0] = "Re-asked for a contact already in context"
        elif re.search(r"phoenix time again", assistant, re.IGNORECASE):
            scores[0] = 0
            reasons[0] = "Re-asked timezone already answered"

        if len(assistant) > 400 or re.search(r"great question|here are (some )?options", assistant, re.I):
            scores[1] = 0
            reasons[1] = "Too long or bot-like filler"
        elif len(assistant) > 220:
            scores[1] = 1
            reasons[1] = "Partly long for texting style"

        if re.search(r"would you like me to|want me to\?", assistant, re.IGNORECASE) and not re.search(
            r"draft|staged|reminder set|saved", assistant, re.IGNORECASE
        ):
            scores[2] = 0
            reasons[2] = "Stalled on offering instead of doing"
        elif re.search(r"i can .+ if you", assistant, re.IGNORECASE):
            scores[2] = 1
            reasons[2] = "Partly advances work"

        if hard["H1"] or hard["H2"]:
            scores[3] = 0
            reasons[3] = "Invented fact or unapproved send claim"
        elif re.search(r"i couldn't find|don't have", assistant, re.IGNORECASE):
            scores[3] = 2
            reasons[3] = "Honest gap without inventing"

        is_draft = "draft" in assistant.lower() or "send to send" in assistant.lower()
        if is_draft or case.get("category") == "send_draft":
            if not re.search(r"^Why:\s*.+", assistant, re.IGNORECASE | re.MULTILINE):
                scores[4] = 0
                reasons[4] = "Draft missing one-line Why"
            elif detect_bad_why(assistant, owner):
                scores[4] = 0
                scores[2] = 1
                reasons[4] = "Why restates trigger instead of real reason"
                reasons[2] = "Draft quality not shippable without a real Why"
            else:
                scores[4] = 2
                reasons[4] = "Why names real reason"
        else:
            scores[4] = 2
            reasons[4] = "n/a (no draft expected)"

        return {
            "line_scores": scores,
            "line_reasons": reasons,
            "hard_fails": hard,
            "grader_note": "fixture route",
            "route": "fixture",
        }
