#!/usr/bin/env python3
"""Fixture judge route for synthetic CI cases (no external model).

Uses per-case fixture_scores when present; otherwise mirrors the
deterministic grader so CI exercises the judge-merge path.
"""

from __future__ import annotations

from typing import Any

from grader.hard_fail import detect_hard_fails
from grader.routes.deterministic import DeterministicRoute


def build_route():
    return FixtureRoute()


class FixtureRoute:
    name = "fixture"

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
        out = DeterministicRoute().grade(case, run)
        out["route"] = "fixture"
        out["grader_note"] = "fixture route"
        return out
